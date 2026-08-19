"""Módulo de Uniformes: cadastro de funcionários, estoque próprio de itens de
uniforme e entregas (baixas) — sem depender do estoque de peças.

Regra central: o saldo é por TAMANHO. Toda mudança de saldo passa por
`_mover_saldo()`, que exige o tamanho, confere se ele pertence ao tipo do item
e só então soma ou subtrai naquele tamanho. Entrada, saída, ajuste, entrega e
cancelamento de entrega usam essa mesma função — é o que garante que a regra
valha em qualquer caminho, hoje e nos que forem criados depois.
"""
from flask import Blueprint, jsonify, request

from extensions import db
from models import (ROTULOS_TIPO_TAMANHO, TAMANHOS_UNIFORME, EntregaUniforme,
                    Funcionario, ItemUniforme, MovimentoUniforme,
                    garantir_saldos, normalizar_tipo_tamanho,
                    proximo_codigo_item_uniforme, recalcular_total_uniforme,
                    saldo_do_tamanho)
from services.crud import (ErroNegocio, editar_tela, registrar_crud, registrar_log,
                           visualizar_tela)
from services.tempo import hoje, ler_data

bp_uniformes = Blueprint("uniformes", __name__, url_prefix="/api")


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
    """Código gerado pelo sistema (0001, 0002...) e tipo de tamanho normalizado
    ('Calçado' vira 'calcado'), para o resto do módulo comparar sem susto."""
    if anterior is None:
        obj.codigo = proximo_codigo_item_uniforme()
    obj.tipo_tamanho = normalizar_tipo_tamanho(
        dados.get("tipo_tamanho") or obj.tipo_tamanho)


registrar_crud(
    bp_uniformes, "itens_uniforme", ItemUniforme,
    campos={"codigo": "str", "descricao": "str", "tipo_tamanho": "str",
            "unidade": "str", "estoque_minimo": "float", "ativo": "bool"},
    ordem=ItemUniforme.codigo, obrigatorios=("descricao",), tela="uniformes",
    antes_salvar=_antes_item_uniforme)


# ------------------------------------------------------ saldos por tamanho
def _item(item_id):
    item = db.session.get(ItemUniforme, int(item_id or 0))
    if not item:
        raise ErroNegocio("Item de uniforme não encontrado.")
    garantir_saldos(item)
    return item


def _validar_tamanho(item, tamanho):
    """O tamanho é obrigatório e tem que pertencer ao tipo do item —
    pedir 'P' de um sapato, ou '42' de uma camisa, é erro de digitação."""
    escolhido = (tamanho or "").strip()
    if not escolhido:
        raise ErroNegocio(f"Escolha o tamanho de {item.descricao}. "
                          "O estoque de uniformes é controlado por tamanho.")
    previstos = item.tamanhos_previstos()
    for t in previstos:
        if t.lower() == escolhido.lower():
            return t
    rotulo = ROTULOS_TIPO_TAMANHO.get(normalizar_tipo_tamanho(item.tipo_tamanho), "Roupa")
    raise ErroNegocio(f"Tamanho '{escolhido}' não existe em {item.descricao} "
                      f"({rotulo}). Tamanhos possíveis: {', '.join(previstos)}.")


def _mover_saldo(item, tamanho, tipo, quantidade, documento=None,
                 observacao=None, entrega_id=None, data=None):
    """Única porta de entrada para mexer no saldo. Registra o movimento e
    devolve a linha de saldo já atualizada."""
    tamanho = _validar_tamanho(item, tamanho)
    quantidade = float(quantidade or 0)
    if quantidade <= 0:
        raise ErroNegocio("Informe uma quantidade maior que zero.")

    saldo = saldo_do_tamanho(item, tamanho)
    atual = saldo.quantidade or 0

    if tipo == "entrada":
        saldo.quantidade = atual + quantidade
    elif tipo == "saida":
        if quantidade > atual:
            raise ErroNegocio(
                f"Saldo insuficiente de {item.descricao} tamanho {tamanho} "
                f"(disponível: {atual:g}). O saldo dos outros tamanhos não é usado.")
        saldo.quantidade = atual - quantidade
    elif tipo == "ajuste":
        saldo.quantidade = quantidade
    else:
        raise ErroNegocio("Tipo de movimento inválido.")

    db.session.add(MovimentoUniforme(
        data=data or hoje(), item_id=item.id, tamanho=tamanho, tipo=tipo,
        quantidade=quantidade, documento=documento, entrega_id=entrega_id,
        observacao=observacao))
    recalcular_total_uniforme(item)
    return saldo


@bp_uniformes.get("/uniformes/tamanhos")
@visualizar_tela("uniformes")
def listar_tamanhos_possiveis():
    """Alimenta os campos de tamanho da tela, por tipo de produto."""
    return jsonify({"tipos": ROTULOS_TIPO_TAMANHO, "tamanhos": TAMANHOS_UNIFORME})


@bp_uniformes.get("/itens_uniforme/<int:item_id>/saldos")
@visualizar_tela("uniformes")
def listar_saldos_item(item_id):
    try:
        item = _item(item_id)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 404
    return jsonify(item.to_dict())


@bp_uniformes.put("/itens_uniforme/<int:item_id>/saldos")
@editar_tela("uniformes")
def salvar_minimos_item(item_id):
    """Grava o estoque mínimo de cada tamanho. O saldo em si NÃO muda aqui —
    saldo só muda por movimento, para nunca existir número sem histórico."""
    dados = request.get_json(silent=True) or {}
    try:
        item = _item(item_id)
        for linha in (dados.get("tamanhos") or []):
            tamanho = _validar_tamanho(item, linha.get("tamanho"))
            saldo = saldo_do_tamanho(item, tamanho)
            saldo.estoque_minimo = max(0, float(linha.get("estoque_minimo") or 0))
        registrar_log("editar", "saldos_uniforme", item.id,
                      f"Mínimos por tamanho: {item.descricao}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(item.to_dict())


@bp_uniformes.get("/uniformes/movimentos")
@visualizar_tela("uniformes")
def listar_movimentos_uniforme():
    q = MovimentoUniforme.query
    if request.args.get("item_id"):
        q = q.filter(MovimentoUniforme.item_id == int(request.args["item_id"]))
    q = _filtro_periodo(MovimentoUniforme.data)(q, request.args)
    return jsonify([m.to_dict() for m in q.order_by(MovimentoUniforme.id.desc()).limit(500)])


@bp_uniformes.post("/uniformes/movimentos")
@editar_tela("uniformes")
def criar_movimento_uniforme():
    """Entrada, saída ou ajuste de saldo de UM tamanho (não é uma entrega)."""
    dados = request.get_json(silent=True) or {}
    try:
        item = _item(dados.get("item_id"))
        tipo = dados.get("tipo", "entrada")
        saldo = _mover_saldo(
            item, dados.get("tamanho"), tipo, dados.get("quantidade"),
            documento=dados.get("documento"), observacao=dados.get("observacao"))
        registrar_log("criar", "movimentos_uniforme", item.id,
                      f"{tipo}: {item.codigo} tam. {saldo.tamanho}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True, "item": item.to_dict()}), 201


# --------------------------------------------- Entregas de uniforme (baixas)
@bp_uniformes.get("/entregas_uniforme")
@visualizar_tela("uniformes")
def listar_entregas_uniforme():
    q = EntregaUniforme.query
    if request.args.get("funcionario_id"):
        q = q.filter(EntregaUniforme.funcionario_id == int(request.args["funcionario_id"]))
    q = _filtro_periodo(EntregaUniforme.data)(q, request.args)
    q = q.order_by(EntregaUniforme.data.desc(), EntregaUniforme.id.desc())
    return jsonify([e.to_dict() for e in q.all()])


@bp_uniformes.post("/entregas_uniforme")
@editar_tela("uniformes")
def criar_entrega_uniforme():
    """Registra a entrega e dá baixa NO TAMANHO escolhido."""
    dados = request.get_json(silent=True) or {}
    try:
        funcionario_id = dados.get("funcionario_id")
        if not funcionario_id or not dados.get("item_id"):
            raise ErroNegocio("Selecione o funcionário e o item.")
        funcionario = db.session.get(Funcionario, int(funcionario_id))
        if not funcionario:
            raise ErroNegocio("Funcionário não encontrado.")
        item = _item(dados.get("item_id"))

        tamanho = _validar_tamanho(item, dados.get("tamanho"))
        quantidade = float(dados.get("quantidade") or 1)

        tipo_entrega = dados.get("tipo_entrega") or "Novo"
        if tipo_entrega not in ("Novo", "Emergencial"):
            raise ErroNegocio("Tipo de entrega inválido.")

        data_entrega = ler_data(dados.get("data"), "data da entrega") or hoje()
        entrega = EntregaUniforme(
            data=data_entrega, funcionario_id=funcionario.id, item_id=item.id,
            tamanho=tamanho, tipo_entrega=tipo_entrega, quantidade=quantidade,
            observacao=(dados.get("observacao") or "").strip() or None)
        db.session.add(entrega)
        db.session.flush()

        _mover_saldo(item, tamanho, "saida", quantidade,
                     documento=f"Entrega {tipo_entrega.lower()} — {funcionario.nome}",
                     observacao=f"Tamanho: {tamanho}", entrega_id=entrega.id,
                     data=data_entrega)

        registrar_log("criar", "entregas_uniforme", entrega.id,
                      f"{item.descricao} tam. {tamanho} para {funcionario.nome}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(entrega.to_dict()), 201


@bp_uniformes.delete("/entregas_uniforme/<int:entrega_id>")
@editar_tela("uniformes")
def excluir_entrega_uniforme(entrega_id):
    """Cancela a entrega e devolve a quantidade ao MESMO tamanho."""
    entrega = db.session.get(EntregaUniforme, entrega_id)
    if not entrega:
        return jsonify({"erro": "Entrega não encontrada."}), 404
    try:
        item = entrega.item
        descricao = item.descricao if item else ""
        if item:
            garantir_saldos(item)
            if entrega.tamanho:
                _mover_saldo(item, entrega.tamanho, "entrada", entrega.quantidade,
                             documento="Estorno de entrega",
                             observacao=f"Cancelamento da entrega #{entrega.id}")
            else:
                # Entrega antiga, de antes do controle por tamanho: não há de
                # qual saldo devolver. Ela sai do histórico e o estoque fica
                # como está — se precisar, lance a entrada pelo tamanho.
                registrar_log("editar", "entregas_uniforme", entrega.id,
                              "Entrega sem tamanho: nada devolvido ao estoque")
        registrar_log("excluir", "entregas_uniforme", entrega_id, f"Estornado: {descricao}")
        db.session.delete(entrega)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception:
        db.session.rollback()
        return jsonify({"erro": "Não foi possível cancelar essa entrega."}), 400
    return jsonify({"ok": True})


# ------------------------------------------------- listas para impressão
def _itens_com_saldos(somente_ativos=True):
    q = ItemUniforme.query
    if somente_ativos:
        q = q.filter(ItemUniforme.ativo.is_(True))
    itens = q.order_by(ItemUniforme.descricao).all()
    criados = sum(garantir_saldos(item) for item in itens)
    if criados:
        db.session.commit()
    return itens


@bp_uniformes.get("/uniformes/compra")
@visualizar_tela("uniformes")
def lista_de_compra():
    """O que comprar: só os tamanhos abaixo do mínimo, com a quantidade que
    falta para chegar nele."""
    resultado = []
    for item in _itens_com_saldos():
        faltantes = []
        for saldo in item.saldos_ordenados():
            linha = saldo.to_dict()
            if linha["abaixo_minimo"] and linha["falta_comprar"] > 0:
                faltantes.append(linha)
        if not faltantes:
            continue
        resultado.append({
            "id": item.id, "codigo": item.codigo, "descricao": item.descricao,
            "unidade": item.unidade,
            "tipo_tamanho_rotulo": ROTULOS_TIPO_TAMANHO.get(
                normalizar_tipo_tamanho(item.tipo_tamanho), "Roupa"),
            "tamanhos": faltantes,
            "total_comprar": round(sum(t["falta_comprar"] for t in faltantes), 3)})
    return jsonify(resultado)


@bp_uniformes.get("/uniformes/posicao")
@visualizar_tela("uniformes")
def posicao_do_estoque():
    """Todos os itens com o saldo de cada tamanho."""
    return jsonify([item.to_dict() for item in _itens_com_saldos()])
