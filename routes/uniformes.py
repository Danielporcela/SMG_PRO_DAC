"""Módulo de Uniformes: cadastro de funcionários, estoque próprio de itens de
uniforme e entregas (baixas) — sem depender do estoque de peças.
"""
from flask import Blueprint, jsonify, request

from extensions import db
from models import EntregaUniforme, Funcionario, ItemUniforme, MovimentoUniforme, proximo_codigo_item_uniforme
from services.crud import (ErroNegocio, editar_tela, registrar_crud, registrar_log,
                           visualizar_tela)
from services.tempo import hoje, ler_data

bp_uniformes = Blueprint("uniformes", __name__)


def _filtro_periodo(campo):
    def filtrar(q, args):
        inicio = ler_data(args.get("inicio"), "início do período")
        fim = ler_data(args.get("fim"), "fim do período")
        if inicio:
            q = q.filter(campo >= inicio)
        if fim:
            q = q.filter(campo <= fim)
        return q
    return filtrar


# --------------------------------------------------------- Funcionários
registrar_crud(
    bp_uniformes, "funcionarios", Funcionario,
    campos={"nome": "str", "matricula": "str", "cargo": "str", "setor": "str",
            "telefone": "str", "ativo": "bool"},
    ordem=Funcionario.nome, obrigatorios=("nome",), tela="funcionarios")


# ---------------------------------------------- Estoque próprio de uniformes
def _antes_item_uniforme(obj, dados, anterior):
    """O código é sempre gerado pelo sistema (0001, 0002...), igual ao
    estoque de peças — o campo fica travado na tela."""
    if anterior is None:
        obj.codigo = proximo_codigo_item_uniforme()


registrar_crud(
    bp_uniformes, "itens_uniforme", ItemUniforme,
    campos={"codigo": "str", "descricao": "str", "unidade": "str",
            "quantidade": "float", "estoque_minimo": "float", "ativo": "bool"},
    ordem=ItemUniforme.codigo, obrigatorios=("descricao",), tela="uniformes",
    antes_salvar=_antes_item_uniforme)


@bp_uniformes.get("/api/uniformes/movimentos")
@visualizar_tela("uniformes")
def listar_movimentos_uniforme():
    q = MovimentoUniforme.query
    if request.args.get("item_id"):
        q = q.filter(MovimentoUniforme.item_id == int(request.args["item_id"]))
    q = _filtro_periodo(MovimentoUniforme.data)(q, request.args)
    return jsonify([m.to_dict() for m in q.order_by(MovimentoUniforme.id.desc()).limit(500)])


@bp_uniformes.post("/api/uniformes/movimentos")
@editar_tela("uniformes")
def criar_movimento_uniforme():
    """Entrada de estoque ou ajuste manual de saldo (não é uma entrega)."""
    dados = request.get_json(silent=True) or {}
    try:
        item = db.session.get(ItemUniforme, int(dados.get("item_id") or 0))
        if not item:
            raise ErroNegocio("Item de uniforme não encontrado.")
        tipo = dados.get("tipo", "entrada")
        quantidade = float(dados.get("quantidade") or 0)
        if quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")
        if tipo == "entrada":
            item.quantidade = (item.quantidade or 0) + quantidade
        elif tipo == "saida":
            if quantidade > (item.quantidade or 0):
                raise ErroNegocio("Saldo insuficiente para essa saída.")
            item.quantidade = (item.quantidade or 0) - quantidade
        elif tipo == "ajuste":
            item.quantidade = quantidade
        else:
            raise ErroNegocio("Tipo de movimento inválido.")
        db.session.add(MovimentoUniforme(
            item_id=item.id, tipo=tipo, quantidade=quantidade,
            documento=dados.get("documento"), observacao=dados.get("observacao")))
        registrar_log("criar", "movimentos_uniforme", item.id, f"{tipo}: {item.codigo}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True}), 201


# --------------------------------------------- Entregas de uniforme (baixas)
@bp_uniformes.get("/api/entregas_uniforme")
@visualizar_tela("uniformes")
def listar_entregas_uniforme():
    q = EntregaUniforme.query
    if request.args.get("funcionario_id"):
        q = q.filter(EntregaUniforme.funcionario_id == int(request.args["funcionario_id"]))
    q = _filtro_periodo(EntregaUniforme.data)(q, request.args)
    q = q.order_by(EntregaUniforme.data.desc(), EntregaUniforme.id.desc())
    return jsonify([e.to_dict() for e in q.all()])


@bp_uniformes.post("/api/entregas_uniforme")
@editar_tela("uniformes")
def criar_entrega_uniforme():
    """Registra a entrega e já dá baixa no saldo único do item — o tamanho
    escolhido aqui é só uma informação da entrega, não afeta qual saldo é
    debitado (não existe saldo separado por tamanho)."""
    dados = request.get_json(silent=True) or {}
    try:
        funcionario_id = dados.get("funcionario_id")
        item_id = dados.get("item_id")
        if not funcionario_id or not item_id:
            raise ErroNegocio("Selecione o funcionário e o item.")
        funcionario = db.session.get(Funcionario, int(funcionario_id))
        if not funcionario:
            raise ErroNegocio("Funcionário não encontrado.")
        item = db.session.get(ItemUniforme, int(item_id))
        if not item:
            raise ErroNegocio("Item de uniforme não encontrado.")

        quantidade = float(dados.get("quantidade") or 1)
        if quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")
        if quantidade > (item.quantidade or 0):
            raise ErroNegocio(f"Saldo insuficiente de {item.descricao} "
                              f"(disponível: {item.quantidade or 0:g}).")

        tipo_entrega = dados.get("tipo_entrega") or "Novo"
        if tipo_entrega not in ("Novo", "Emergencial"):
            raise ErroNegocio("Tipo de entrega inválido.")

        entrega = EntregaUniforme(
            data=ler_data(dados.get("data"), "data da entrega") or hoje(),
            funcionario_id=funcionario.id, item_id=item.id,
            tamanho=(dados.get("tamanho") or "").strip() or None,
            tipo_entrega=tipo_entrega, quantidade=quantidade,
            observacao=(dados.get("observacao") or "").strip() or None)
        db.session.add(entrega)
        db.session.flush()

        item.quantidade = (item.quantidade or 0) - quantidade
        db.session.add(MovimentoUniforme(
            item_id=item.id, tipo="saida", quantidade=quantidade,
            documento=f"Entrega {tipo_entrega.lower()} — {funcionario.nome}",
            entrega_id=entrega.id,
            observacao=f"Tamanho: {entrega.tamanho}" if entrega.tamanho else None))

        registrar_log("criar", "entregas_uniforme", entrega.id,
                      f"{item.descricao} para {funcionario.nome}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(entrega.to_dict()), 201


@bp_uniformes.delete("/api/entregas_uniforme/<int:entrega_id>")
@editar_tela("uniformes")
def excluir_entrega_uniforme(entrega_id):
    """Cancela a entrega e devolve a quantidade ao estoque."""
    entrega = db.session.get(EntregaUniforme, entrega_id)
    if not entrega:
        return jsonify({"erro": "Entrega não encontrada."}), 404
    try:
        item = entrega.item
        if item:
            item.quantidade = (item.quantidade or 0) + (entrega.quantidade or 0)
            db.session.add(MovimentoUniforme(
                item_id=item.id, tipo="entrada", quantidade=entrega.quantidade,
                documento="Estorno de entrega", entrega_id=None,
                observacao=f"Cancelamento da entrega #{entrega.id}"))
        registrar_log("excluir", "entregas_uniforme", entrega_id,
                      f"Estornado: {entrega.item.descricao if entrega.item else ''}")
        db.session.delete(entrega)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"erro": "Não foi possível cancelar essa entrega."}), 400
    return jsonify({"ok": True})
