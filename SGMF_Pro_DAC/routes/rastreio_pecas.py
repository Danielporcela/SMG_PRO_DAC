"""Rastreio de peças por número de série/identificação.

Módulo somente de leitura: dado um número (ex.: "5555" do espelho
retrovisor), mostra a peça a que ele pertence, o status atual (em estoque,
em uso em qual veículo, ou descartado) e a linha do tempo completa de
movimentações — quando entrou, em quais OS/veículos já foi instalado e
removido, até chegar no status de hoje.
"""
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from models import PecaSerial

bp_rastreio_pecas = Blueprint("rastreio_pecas", __name__)

_PESOS = {"nenhum": 0, "visualizar": 1, "editar": 2}
_TELAS_LIBERADAS = ("estoque", "manutencao")
LIMITE_RESULTADOS = 50


def pode_rastrear():
    """Mesma regra da Pesquisa de peças: administrador sempre pode; os
    demais precisam enxergar Estoque ou Ordens de serviço.
    """
    if session.get("perfil") == "admin":
        return True
    permissoes = session.get("permissoes") or {}
    return any(_PESOS.get(permissoes.get(tela, "nenhum"), 0) >= 1
               for tela in _TELAS_LIBERADAS)


@bp_rastreio_pecas.get("/rastreio-pecas")
def pagina():
    if not session.get("usuario_id"):
        return redirect(url_for("auth.login"))
    if not pode_rastrear():
        return render_template(
            "erro.html", codigo=403,
            mensagem="Seu acesso não permite consultar o rastreio de peças."), 403
    return render_template("rastreio_pecas.html", pagina="rastreio_pecas")


@bp_rastreio_pecas.get("/api/rastreio-pecas")
def api_rastreio():
    if not session.get("usuario_id"):
        return jsonify({"erro": "Sessão encerrada. Entre no sistema novamente."}), 401
    if not pode_rastrear():
        return jsonify({"erro": "Seu acesso não permite consultar peças."}), 403

    termo = (request.args.get("numero") or "").strip()
    if not termo:
        return jsonify({"total": 0, "resultados": []})

    consulta = (PecaSerial.query
               .filter(PecaSerial.numero_serie.ilike(f"%{termo}%"))
               .order_by(PecaSerial.numero_serie)
               .limit(LIMITE_RESULTADOS).all())

    resultados = []
    for serial in consulta:
        dado = serial.to_dict()
        dado["historico"] = [m.to_dict() for m in serial.movimentos]
        resultados.append(dado)

    return jsonify({"total": len(resultados), "limite": LIMITE_RESULTADOS,
                    "resultados": resultados})
