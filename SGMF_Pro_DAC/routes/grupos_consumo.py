"""Tela e API para baixa de estoque por grupos de consumo interno."""
from flask import Blueprint, jsonify, request

from extensions import db
from models import GrupoConsumo, Peca
from services.calculos import movimentar_estoque
from services.crud import ErroNegocio, editar_tela, registrar_log, visualizar_tela
from services.grupos_consumo import custos_por_grupo, eh_grupo_padrao, movimentos_por_grupo
from services.tempo import hoje, ler_data


bp_grupos_consumo = Blueprint("grupos_consumo", __name__, url_prefix="/api/grupos-consumo")


def _periodo():
    fim = ler_data(request.args.get("fim"), "fim do período") or hoje()
    inicio = ler_data(request.args.get("inicio"), "início do período") or fim.replace(day=1)
    if inicio > fim:
        raise ErroNegocio("A data inicial não pode ser posterior à data final.")
    return inicio, fim


def _grupo(grupo_id):
    grupo = db.session.get(GrupoConsumo, grupo_id)
    if not grupo:
        raise ErroNegocio("Grupo de consumo não encontrado.")
    return grupo


@bp_grupos_consumo.get("")
@visualizar_tela("grupos_consumo")
def listar():
    q = GrupoConsumo.query
    if request.args.get("ativos") == "1":
        q = q.filter(GrupoConsumo.ativo.is_(True))
    return jsonify([g.to_dict() for g in q.order_by(GrupoConsumo.nome).all()])


@bp_grupos_consumo.post("")
@editar_tela("grupos_consumo")
def criar():
    dados = request.get_json(silent=True) or {}
    nome = (dados.get("nome") or "").strip()
    if not nome:
        return jsonify({"erro": "Informe o nome do grupo."}), 400
    if any((g.nome or "").strip().casefold() == nome.casefold() for g in GrupoConsumo.query.all()):
        return jsonify({"erro": "Já existe um grupo de consumo com esse nome."}), 400
    grupo = GrupoConsumo(nome=nome,
                         descricao=(dados.get("descricao") or "").strip() or None,
                         ativo=True)
    db.session.add(grupo)
    db.session.flush()
    registrar_log("criar", "grupos_consumo", grupo.id, grupo.nome)
    db.session.commit()
    return jsonify(grupo.to_dict()), 201


@bp_grupos_consumo.put("/<int:grupo_id>")
@editar_tela("grupos_consumo")
def editar(grupo_id):
    try:
        grupo = _grupo(grupo_id)
        dados = request.get_json(silent=True) or {}
        nome = (dados.get("nome") or grupo.nome or "").strip()
        if not nome:
            raise ErroNegocio("Informe o nome do grupo.")
        if eh_grupo_padrao(grupo.nome) and nome.casefold() != (grupo.nome or "").strip().casefold():
            raise ErroNegocio("Este grupo padrão não pode ser renomeado para preservar o histórico antigo.")
        repetido = any(g.id != grupo.id and (g.nome or "").strip().casefold() == nome.casefold()
                       for g in GrupoConsumo.query.all())
        if repetido:
            raise ErroNegocio("Já existe um grupo de consumo com esse nome.")
        grupo.nome = nome
        grupo.descricao = (dados.get("descricao") or "").strip() or None
        if "ativo" in dados:
            grupo.ativo = dados.get("ativo") in (True, "true", "1", 1)
        registrar_log("editar", "grupos_consumo", grupo.id, grupo.nome)
        db.session.commit()
        return jsonify(grupo.to_dict())
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400


@bp_grupos_consumo.post("/retiradas")
@editar_tela("grupos_consumo")
def retirar():
    dados = request.get_json(silent=True) or {}
    try:
        grupo = _grupo(int(dados.get("grupo_consumo_id") or 0))
        if not grupo.ativo:
            raise ErroNegocio("Este grupo está desativado e não aceita novas retiradas.")
        peca = db.session.get(Peca, int(dados.get("peca_id") or 0))
        if not peca:
            raise ErroNegocio("Selecione uma peça válida.")
        quantidade = float(dados.get("quantidade") or 0)
        observacao_extra = (dados.get("observacao") or "").strip()
        observacao = f"Retirada para {grupo.nome}"
        if observacao_extra:
            observacao = f"{observacao}. {observacao_extra}"
        movimentar_estoque(
            peca.id,
            "saida",
            quantidade,
            peca.custo_unitario,
            documento=(dados.get("documento") or "").strip() or None,
            observacao=observacao,
            grupo_consumo_id=grupo.id,
        )
        registrar_log("retirar", "grupos_consumo", grupo.id,
                      f"{peca.codigo} | {quantidade:g} {peca.unidade} | {grupo.nome}")
        db.session.commit()
        db.session.refresh(peca)
        return jsonify({"ok": True, "grupo": grupo.to_dict(), "peca": peca.to_dict()}), 201
    except (ErroNegocio, ValueError, TypeError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400


@bp_grupos_consumo.get("/resumo")
@visualizar_tela("grupos_consumo")
def resumo():
    try:
        inicio, fim = _periodo()
        grupos = custos_por_grupo(inicio, fim)
        return jsonify({
            "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
            "grupos": grupos,
            "total_realizado": round(sum(g["realizado"] for g in grupos), 2),
            "total_meta": round(sum(g["meta"] for g in grupos), 2),
            "total_movimentos": sum(g["movimentos"] for g in grupos),
        })
    except ErroNegocio as e:
        return jsonify({"erro": str(e)}), 400


@bp_grupos_consumo.get("/movimentos")
@visualizar_tela("grupos_consumo")
def movimentos():
    try:
        inicio, fim = _periodo()
        grupo_id = request.args.get("grupo_consumo_id", type=int)
        return jsonify(movimentos_por_grupo(inicio, fim, grupo_id))
    except ErroNegocio as e:
        return jsonify({"erro": str(e)}), 400
