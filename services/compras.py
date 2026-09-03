"""Módulo — Ordens de compra.

Fluxo pedido:

    Pendente ──▶ Aprovada ──▶ Comprada
        └─────▶ Reprovada ──▶ (reabrir) ──▶ Pendente

A ordem nasce Pendente com a operação lançando os itens. O financeiro
Aprova ou Reprova, e depois de comprar marca como Comprada. Aprovar,
reprovar e comprar exigem nível 'editar' na tela 'compras' — é assim que
se separa quem pede de quem autoriza (dê 'visualizar' a quem só solicita).

Nada aqui mexe no saldo do estoque: a ordem de compra é o documento do
pedido. A entrada continua sendo feita pela nota fiscal ou pelo movimento
manual, como sempre foi.

Os itens seguem o mesmo desenho do ItemOS: `peca_id` preenchido quando a
peça foi escolhida no estoque, ou só `descricao` quando foi escrita à mão.
"""
from datetime import datetime

from flask import Blueprint, jsonify, request, session

from extensions import db
from models import ItemOrdemCompra, OrdemCompra, Peca, proximo_numero_ordem_compra
from services.crud import (ErroNegocio, editar_tela, registrar_crud, registrar_log,
                           visualizar_tela)
from services.tempo import hoje

# Se o app.py registrar as blueprints já com url_prefix="/api"
# (app.register_blueprint(bp_compras, url_prefix="/api")), troque a linha
# abaixo por:  bp_compras = Blueprint("compras", __name__)
bp_compras = Blueprint("compras", __name__, url_prefix="/api")

TELA = "compras"
ROTA = "ordens_compra"


# --------------------------------------------------------------- auxiliares
def _usuario():
    return session.get("usuario_nome", "sistema")


def _data(texto):
    try:
        return datetime.strptime(str(texto)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _numero(valor, padrao=0.0):
    try:
        return float(str(valor).replace(",", "."))
    except (ValueError, TypeError):
        return padrao


def _exigir_pendente(ordem):
    if ordem.status != "Pendente":
        raise ErroNegocio(
            f"Esta ordem já está {ordem.status.lower()} e não aceita mais alteração de itens.")


def _resposta(ordem):
    return jsonify(ordem.to_dict(com_itens=True))


# ------------------------------------------------------- CRUD do cabeçalho
def _filtrar(q, args):
    """Mesmo filtro de período das outras telas (inicio/fim), mais um filtro
    opcional por situação usado pelos atalhos do topo da tela."""
    inicio, fim = _data(args.get("inicio")), _data(args.get("fim"))
    if inicio:
        q = q.filter(OrdemCompra.data_solicitacao >= inicio)
    if fim:
        q = q.filter(OrdemCompra.data_solicitacao <= fim)
    status = (args.get("status") or "").strip()
    if status:
        q = q.filter(OrdemCompra.status == status)
    return q


def _antes_salvar(obj, dados, anterior):
    if anterior is None:                     # criação
        obj.numero = obj.numero or proximo_numero_ordem_compra()
        obj.solicitante = obj.solicitante or _usuario()
        obj.status = "Pendente"              # status só muda pelas rotas de fluxo
        if not obj.data_solicitacao:
            obj.data_solicitacao = hoje()
    elif anterior.get("status") != "Pendente":
        raise ErroNegocio("Só dá para alterar uma ordem que ainda está Pendente. "
                          "Reabra a ordem reprovada ou abra uma nova.")


def _antes_excluir(obj):
    if obj.status in ("Aprovada", "Comprada"):
        raise ErroNegocio(f"Uma ordem {obj.status.lower()} não pode ser excluída — "
                          "ela já faz parte do histórico de aprovação.")


# `status` fica de fora dos campos aceitos de propósito: quem muda a situação
# são as rotas /aprovar, /reprovar e /comprar, que registram quem decidiu.
registrar_crud(
    bp_compras, ROTA, OrdemCompra,
    campos={
        "data_solicitacao": "date",
        "setor": "str",
        "fornecedor_id": "int",
        "prioridade": "str",
        "justificativa": "str",
        "observacao": "str",
        "solicitante": "str",
    },
    ordem=OrdemCompra.data_solicitacao.desc(),
    obrigatorios=("data_solicitacao", "justificativa"),
    antes_salvar=_antes_salvar,
    antes_excluir=_antes_excluir,
    filtrar=_filtrar,
    tela=TELA,
)


# --------------------------------------------------------- itens da ordem
@bp_compras.get(f"/{ROTA}/<int:ordem_id>/itens")
@visualizar_tela(TELA)
def listar_itens(ordem_id):
    return _resposta(db.get_or_404(OrdemCompra, ordem_id))


@bp_compras.post(f"/{ROTA}/<int:ordem_id>/itens")
@editar_tela(TELA)
def adicionar_item(ordem_id):
    """Adiciona somente itens digitados manualmente."""
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    dados = request.get_json(silent=True) or {}
    try:
        _exigir_pendente(ordem)
        descricao = (dados.get("descricao") or "").strip()
        if not descricao:
            raise ErroNegocio("Digite a descrição do item.")

        item = ItemOrdemCompra(
            ordem_compra_id=ordem.id,
            peca_id=None,
            descricao=descricao[:160],
            unidade="UN",
            quantidade=1,
            valor_unitario=0,
            observacao=None,
        )
        db.session.add(item)
        db.session.flush()
        registrar_log("criar", "itens_ordem_compra", item.id,
                      f"{ordem.numero} · {item.descricao}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"erro": "Não foi possível adicionar o item."}), 400
    return _resposta(ordem)


@bp_compras.delete(f"/{ROTA}/<int:ordem_id>/itens/<int:item_id>")
@editar_tela(TELA)
def remover_item(ordem_id, item_id):
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    item = db.session.get(ItemOrdemCompra, item_id)
    if item is None or item.ordem_compra_id != ordem.id:
        return jsonify({"erro": "Este item não pertence a esta ordem de compra."}), 404
    try:
        _exigir_pendente(ordem)
        db.session.delete(item)
        registrar_log("excluir", "itens_ordem_compra", item_id, ordem.numero or "")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return _resposta(ordem)


# ---------------------------------------------- comprado / entregue (item)
@bp_compras.post(f"/{ROTA}/<int:ordem_id>/itens/<int:item_id>/comprado")
@editar_tela(TELA)
def marcar_item_comprado(ordem_id, item_id):
    """Marca um item lançado à mão como já comprado (fica verde na lista).

    Não tem relação com o saldo de estoque — é só um controle visual de
    quem já foi providenciado dentro da solicitação de compra.
    """
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    item = db.session.get(ItemOrdemCompra, item_id)
    if item is None or item.ordem_compra_id != ordem.id:
        return jsonify({"erro": "Este item não pertence a esta ordem de compra."}), 404
    if item.peca_id:
        return jsonify({"erro": "Esse controle é só para itens lançados à mão, "
                                "sem vínculo com o estoque."}), 400
    item.comprado = not bool(item.comprado)
    item.comprado_por = _usuario() if item.comprado else None
    item.data_compra_item = hoje() if item.comprado else None
    registrar_log("editar", "itens_ordem_compra", item.id,
                  f"{ordem.numero} · {item.descricao} · comprado={item.comprado}")
    db.session.commit()
    return _resposta(ordem)


@bp_compras.post(f"/{ROTA}/<int:ordem_id>/itens/<int:item_id>/entregue")
@visualizar_tela(TELA)
def marcar_item_entregue(ordem_id, item_id):
    """Marca o item como entregue e o retira da lista. Não usa DELETE,
    portanto não aciona a senha administrativa global de exclusão."""
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    item = db.session.get(ItemOrdemCompra, item_id)
    if item is None or item.ordem_compra_id != ordem.id:
        return jsonify({"erro": "Este item não pertence a esta ordem de compra."}), 404
    db.session.delete(item)
    registrar_log("excluir", "itens_ordem_compra", item_id,
                  f"{ordem.numero} · entregue")
    db.session.commit()
    return _resposta(ordem)


# ------------------------------------------------------------- fluxo/status
@bp_compras.post(f"/{ROTA}/<int:ordem_id>/aprovar")
@editar_tela(TELA)
def aprovar(ordem_id):
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    if ordem.status != "Pendente":
        return jsonify({"erro": f"Só uma ordem Pendente pode ser aprovada "
                                f"(esta está {ordem.status.lower()})."}), 400
    if not ordem.itens:
        return jsonify({"erro": "Lance ao menos um item antes de aprovar."}), 400
    ordem.status = "Aprovada"
    ordem.aprovado_por = _usuario()
    ordem.data_aprovacao = hoje()
    ordem.motivo_reprovacao = None
    registrar_log("editar", ROTA, ordem.id, f"aprovada por {ordem.aprovado_por}")
    db.session.commit()
    return _resposta(ordem)


@bp_compras.post(f"/{ROTA}/<int:ordem_id>/reprovar")
@editar_tela(TELA)
def reprovar(ordem_id):
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    dados = request.get_json(silent=True) or {}
    motivo = (dados.get("motivo") or "").strip()
    if ordem.status != "Pendente":
        return jsonify({"erro": f"Só uma ordem Pendente pode ser reprovada "
                                f"(esta está {ordem.status.lower()})."}), 400
    if not motivo:
        return jsonify({"erro": "Escreva o motivo da reprovação — é ele que volta "
                                "para quem pediu."}), 400
    ordem.status = "Reprovada"
    ordem.motivo_reprovacao = motivo[:200]
    ordem.aprovado_por = _usuario()
    ordem.data_aprovacao = hoje()
    registrar_log("editar", ROTA, ordem.id, f"reprovada por {ordem.aprovado_por}: {motivo[:80]}")
    db.session.commit()
    return _resposta(ordem)


@bp_compras.post(f"/{ROTA}/<int:ordem_id>/comprar")
@editar_tela(TELA)
def comprar(ordem_id):
    """Marca o pedido como comprado. Continua sem tocar no estoque — a peça
    entra quando a nota fiscal for lançada."""
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    if ordem.status != "Aprovada":
        return jsonify({"erro": "Só uma ordem Aprovada pode ser marcada como comprada."}), 400
    ordem.status = "Comprada"
    ordem.comprado_por = _usuario()
    ordem.data_compra = hoje()
    registrar_log("editar", ROTA, ordem.id, f"comprada por {ordem.comprado_por}")
    db.session.commit()
    return _resposta(ordem)


@bp_compras.post(f"/{ROTA}/<int:ordem_id>/reabrir")
@editar_tela(TELA)
def reabrir(ordem_id):
    """Ordem reprovada volta a Pendente para ser corrigida e reenviada —
    evita ter que redigitar tudo quando o financeiro pede um ajuste."""
    ordem = db.get_or_404(OrdemCompra, ordem_id)
    if ordem.status != "Reprovada":
        return jsonify({"erro": "Só uma ordem Reprovada pode ser reaberta."}), 400
    ordem.status = "Pendente"
    ordem.aprovado_por = None
    ordem.data_aprovacao = None
    registrar_log("editar", ROTA, ordem.id, f"reaberta por {_usuario()}")
    db.session.commit()
    return _resposta(ordem)
