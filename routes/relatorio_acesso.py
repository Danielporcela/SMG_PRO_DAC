"""API do Relatório de acesso (somente administrador)."""
from flask import Blueprint, jsonify, request

from services.crud import perfil_obrigatorio
from services.relatorio_acesso import acessos_do_dia
from services.tempo import hoje, ler_data

bp_relatorio_acesso = Blueprint("relatorio_acesso", __name__, url_prefix="/api")


@bp_relatorio_acesso.get("/relatorio-acesso")
@perfil_obrigatorio("admin")
def relatorio_acesso():
    """?data=AAAA-MM-DD — acessos (logins) dos usuários na data escolhida."""
    dia = ler_data(request.args.get("data")) or hoje()
    return jsonify(acessos_do_dia(dia))
