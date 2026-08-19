"""Pesquisa de peças — consulta rápida por código, referência ou nome.

Módulo somente de leitura: não grava nada no banco, não altera saldo e não
mexe em nenhuma tela que já existe. Serve para achar uma peça no balcão
sem precisar rolar a lista inteira do Estoque.

A busca ignora acento e maiúscula/minúscula e aceita várias palavras:
"cubo roda" encontra "Cubo de roda dianteiro VW Delivery". No código, a
pontuação também é ignorada: "fil001" encontra "FIL-001".
"""
import unicodedata

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

from extensions import db
from models import Peca

bp_busca_pecas = Blueprint("busca_pecas", __name__)

# Quantas linhas no máximo voltam para a tela de uma vez. O total encontrado
# continua sendo informado, para a pessoa saber que precisa refinar a busca.
LIMITE_RESULTADOS = 300

_PESOS = {"nenhum": 0, "visualizar": 1, "editar": 2}
_TELAS_LIBERADAS = ("estoque", "manutencao")


def pode_pesquisar():
    """Mesma regra usada no link do menu: administrador sempre pode; os
    demais precisam enxergar Estoque ou Ordens de serviço.
    """
    if session.get("perfil") == "admin":
        return True
    permissoes = session.get("permissoes") or {}
    return any(_PESOS.get(permissoes.get(tela, "nenhum"), 0) >= 1
               for tela in _TELAS_LIBERADAS)


def normalizar(texto):
    """Minúsculo e sem acento, para comparar sem exigir digitação exata."""
    if not texto:
        return ""
    decomposto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in decomposto if not unicodedata.combining(c)).lower().strip()


def compactar(texto):
    """Só letras e números — faz 'fil001' encontrar 'FIL-001'."""
    return "".join(c for c in normalizar(texto) if c.isalnum())


def _textos_da_peca(peca, modo):
    if modo == "codigo":
        return [peca.codigo, peca.referencia]
    if modo == "nome":
        return [peca.descricao]
    return [peca.codigo, peca.referencia, peca.descricao, peca.grupo,
            peca.localizacao, peca.fornecedor.nome if peca.fornecedor else ""]


def combina(peca, termos, modo):
    """Verdadeiro quando TODAS as palavras digitadas aparecem na peça."""
    partes = _textos_da_peca(peca, modo)
    alvo = " ".join(normalizar(p) for p in partes)
    alvo_compacto = " ".join(compactar(p) for p in partes)
    for termo in termos:
        if termo in alvo:
            continue
        compacto = compactar(termo)
        if compacto and compacto in alvo_compacto:
            continue
        return False
    return True


def precisa_repor(peca):
    """Só considera 'repor' quando existe um mínimo maior que zero."""
    return bool(peca.estoque_minimo) and (peca.quantidade or 0) <= (peca.estoque_minimo or 0)


@bp_busca_pecas.get("/pesquisa-pecas")
def pagina():
    if not session.get("usuario_id"):
        return redirect(url_for("auth.login"))
    if not pode_pesquisar():
        return render_template(
            "erro.html", codigo=403,
            mensagem="Seu acesso não permite consultar o estoque de peças."), 403
    return render_template("busca_pecas.html", pagina="busca_pecas")


@bp_busca_pecas.get("/api/busca-pecas")
def api_busca_pecas():
    if not session.get("usuario_id"):
        return jsonify({"erro": "Sessão encerrada. Entre no sistema novamente."}), 401
    if not pode_pesquisar():
        return jsonify({"erro": "Seu acesso não permite consultar peças."}), 403

    termo = (request.args.get("q") or "").strip()
    modo = (request.args.get("modo") or "tudo").lower()
    if modo not in ("tudo", "codigo", "nome"):
        modo = "tudo"
    grupo = (request.args.get("grupo") or "").strip()
    so_com_saldo = request.args.get("com_saldo") == "1"
    so_repor = request.args.get("repor") == "1"

    consulta = Peca.query
    if grupo:
        consulta = consulta.filter(Peca.grupo == grupo)
    pecas = consulta.order_by(Peca.descricao).all()

    termos = [normalizar(p) for p in termo.split() if p.strip()]

    encontradas = []
    for peca in pecas:
        if termos and not combina(peca, termos, modo):
            continue
        if so_com_saldo and (peca.quantidade or 0) <= 0:
            continue
        if so_repor and not precisa_repor(peca):
            continue
        encontradas.append(peca)

    grupos = sorted({g for (g,) in db.session.query(Peca.grupo).distinct().all() if g})
    valor = sum((p.quantidade or 0) * (p.custo_unitario or 0) for p in encontradas)

    return jsonify({
        "total": len(encontradas),
        "limite": LIMITE_RESULTADOS,
        "valor_total": round(valor, 2),
        "repor": sum(1 for p in encontradas if precisa_repor(p)),
        "grupos": grupos,
        "pecas": [p.to_dict() for p in encontradas[:LIMITE_RESULTADOS]],
    })
