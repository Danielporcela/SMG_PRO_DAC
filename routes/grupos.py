"""Cadastro de grupos de peças — Elétrica, Arrefecimento, Motor, Freios...

Este arquivo é autossuficiente de propósito: traz a página e a API juntas e não
depende de routes/api.py, de services/crud.py nem de templates/lista.html. Isso
permite instalar o módulo mexendo só no app.py e no menu.

A checagem de acesso repete a mesma regra do resto do sistema (perfil admin
passa sempre; os demais dependem da matriz de permissões gravada na sessão),
para que a API não libere o que o menu esconde.
"""
from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

from extensions import db
from models import PADRAO_POR_PERFIL, Grupo, Peca, importar_grupos_das_pecas

bp_grupos = Blueprint("grupos", __name__)

TELA = "grupos"
PESOS = {"nenhum": 0, "visualizar": 1, "editar": 2}


# --------------------------------------------------------------- permissões
def _nivel_do_usuario():
    perfil = session.get("perfil")
    if perfil == "admin":
        return "editar"
    permissoes = session.get("permissoes") or {}
    return permissoes.get(TELA) or PADRAO_POR_PERFIL.get(perfil, "nenhum")


def _pode(minimo="visualizar"):
    return PESOS.get(_nivel_do_usuario(), 0) >= PESOS.get(minimo, 1)


def _bloqueio_api(minimo="visualizar"):
    """Devolve a resposta de recusa, ou None quando o acesso está liberado."""
    if not session.get("usuario_id"):
        return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
    if not _pode(minimo):
        return jsonify({"erro": "Você não tem permissão para esta ação."}), 403
    return None


# -------------------------------------------------------------------- página
@bp_grupos.get("/grupos")
def pagina_grupos():
    if not session.get("usuario_id"):
        return redirect(url_for("auth.login"))
    if not _pode("visualizar"):
        return render_template("erro.html", codigo=403,
                               mensagem="Você não tem acesso ao cadastro de grupos."), 403
    return render_template("grupos.html", tela=TELA,
                           pode_editar=_pode("editar"))


# ----------------------------------------------------------------------- API
@bp_grupos.get("/api/grupos")
def listar_grupos():
    bloqueio = _bloqueio_api("visualizar")
    if bloqueio:
        return bloqueio

    consulta = Grupo.query
    if request.args.get("ativos") == "1":
        consulta = consulta.filter(Grupo.ativo.is_(True))
    busca = (request.args.get("busca") or "").strip().lower()

    itens = [g.to_dict() for g in consulta.order_by(Grupo.nome).all()]
    if busca:
        itens = [g for g in itens
                 if busca in (g["nome"] or "").lower()
                 or busca in (g["descricao"] or "").lower()]
    return jsonify(itens)


@bp_grupos.get("/api/grupos/nomes")
def nomes_grupos():
    """Só os nomes ativos — usado para preencher a lista de grupos da peça."""
    bloqueio = _bloqueio_api("visualizar")
    if bloqueio:
        return bloqueio
    nomes = [g.nome for g in
             Grupo.query.filter(Grupo.ativo.is_(True)).order_by(Grupo.nome).all()]
    return jsonify(nomes)


def _nome_repetido(nome, ignorar_id=None):
    alvo = (nome or "").strip().lower()
    consulta = Grupo.query
    if ignorar_id:
        consulta = consulta.filter(Grupo.id != ignorar_id)
    return any((g.nome or "").strip().lower() == alvo for g in consulta.all())


@bp_grupos.post("/api/grupos")
def criar_grupo():
    bloqueio = _bloqueio_api("editar")
    if bloqueio:
        return bloqueio

    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Informe o nome do grupo."}), 400
    if _nome_repetido(nome):
        return jsonify({"erro": f"Já existe um grupo chamado '{nome}'."}), 400

    grupo = Grupo(nome=nome,
                  descricao=(dados.get("descricao") or "").strip() or None,
                  ativo=dados.get("ativo", True) in (True, "true", "1", 1))
    db.session.add(grupo)
    db.session.commit()
    return jsonify(grupo.to_dict()), 201


@bp_grupos.put("/api/grupos/<int:grupo_id>")
def editar_grupo(grupo_id):
    bloqueio = _bloqueio_api("editar")
    if bloqueio:
        return bloqueio

    grupo = Grupo.query.get(grupo_id)
    if not grupo:
        return jsonify({"erro": "Grupo não encontrado."}), 404

    dados = request.get_json(silent=True) or {}
    nome_novo = (dados.get("nome") or "").strip()
    if not nome_novo:
        return jsonify({"erro": "Informe o nome do grupo."}), 400
    if _nome_repetido(nome_novo, ignorar_id=grupo.id):
        return jsonify({"erro": f"Já existe um grupo chamado '{nome_novo}'."}), 400

    nome_antigo = grupo.nome
    grupo.nome = nome_novo
    grupo.descricao = (dados.get("descricao") or "").strip() or None
    if "ativo" in dados:
        grupo.ativo = dados.get("ativo") in (True, "true", "1", 1)

    # Renomeou: as peças que usavam o nome antigo acompanham, senão ficariam
    # apontando para um grupo que não existe mais.
    renomeadas = 0
    if nome_antigo and nome_antigo != nome_novo:
        renomeadas = (Peca.query.filter(Peca.grupo == nome_antigo)
                      .update({Peca.grupo: nome_novo}, synchronize_session=False))

    db.session.commit()
    resposta = grupo.to_dict()
    resposta["pecas_renomeadas"] = renomeadas
    return jsonify(resposta)


@bp_grupos.delete("/api/grupos/<int:grupo_id>")
def excluir_grupo(grupo_id):
    bloqueio = _bloqueio_api("editar")
    if bloqueio:
        return bloqueio

    grupo = Grupo.query.get(grupo_id)
    if not grupo:
        return jsonify({"erro": "Grupo não encontrado."}), 404

    em_uso = grupo.quantidade_pecas()
    if em_uso:
        return jsonify({"erro": f"Não dá para excluir: {em_uso} peça(s) estão neste "
                                "grupo. Troque o grupo dessas peças ou desative o "
                                "grupo para ele sumir das opções."}), 400

    db.session.delete(grupo)
    db.session.commit()
    return jsonify({"ok": True})


@bp_grupos.post("/api/grupos/importar")
def importar_grupos():
    """Traz para o cadastro os grupos que já estão escritos nas peças."""
    bloqueio = _bloqueio_api("editar")
    if bloqueio:
        return bloqueio
    criados = importar_grupos_das_pecas()
    return jsonify({"criados": criados, "total": len(criados)})
