"""Rotas administrativas para corrigir baixas pendentes de OS antigas."""
from flask import Blueprint, jsonify

from extensions import db
from services.auditoria_estoque import listar_pendencias, regularizar_os, resumir_pendencias
from services.crud import ErroNegocio, perfil_obrigatorio, registrar_log

bp_auditoria_estoque = Blueprint("auditoria_estoque", __name__)


@bp_auditoria_estoque.get("/api/auditoria_estoque_os")
@perfil_obrigatorio("admin")
def listar_auditoria_estoque_os():
    ordens = listar_pendencias()
    return jsonify({"resumo": resumir_pendencias(ordens), "ordens": ordens})


@bp_auditoria_estoque.post("/api/auditoria_estoque_os/<int:os_id>/regularizar")
@perfil_obrigatorio("admin")
def regularizar_auditoria_estoque_os(os_id):
    try:
        ordem, quantidade = regularizar_os(os_id)
        registrar_log(
            "regularizar", "estoque_os", ordem.id,
            f"OS {ordem.numero}: {quantidade} item(ns) com baixa de estoque regularizada"
        )
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível regularizar a OS: {e.__class__.__name__}."}), 400

    ordens = listar_pendencias()
    return jsonify({
        "ok": True,
        "ordem_id": ordem.id,
        "numero": ordem.numero,
        "itens_regularizados": quantidade,
        "resumo": resumir_pendencias(ordens),
    })
