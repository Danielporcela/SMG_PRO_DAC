"""API REST dos módulos: frota, manutenção, combustível, pneus, estoque e orçamento."""
from datetime import date

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func

from extensions import db
from models import (Abastecimento, Fornecedor, ItemNotaFiscal, ItemOS, LogAuditoria,
                    Motorista, MovimentoEstoque, NotaFiscal, Orcamento, OrdemServico, Peca,
                    Pneu, Veiculo)
from services import indicadores
from services.calculos import (baixar_item_os, desvincular_movimentos, devolver_item_os,
                               estornar_nota_fiscal, finalizar_nota_fiscal,
                               marcar_pneu_substituido, movimentar_estoque,
                               proximo_numero_os, recalcular_abastecimento,
                               reverter_pneu_substituido, sincronizar_status_veiculo,
                               validar_km)
from services.crud import (ErroNegocio, aplicar_campos, editar_tela, login_obrigatorio,
                           perfil_obrigatorio, pode_escrever, registrar_crud,
                           registrar_log, visualizar_tela)
from services.tempo import hoje, ler_data

bp_api = Blueprint("api", __name__, url_prefix="/api")


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


# ------------------------------------------------------- Módulo 1: veículos
registrar_crud(
    bp_api, "veiculos", Veiculo,
    campos={"prefixo": "str", "placa": "str", "marca": "str", "modelo": "str",
            "ano": "int", "tipo": "str", "combustivel": "str", "centro_custo": "str",
            "setor": "str", "hodometro": "float", "horimetro": "float", "situacao": "str",
            "km_ultima_troca_oleo": "float", "intervalo_troca_oleo": "float",
            "data_ultima_preventiva": "date", "intervalo_preventiva_dias": "int",
            "orcamento_mensal": "float", "observacao": "str", "ativo": "bool"},
    ordem=Veiculo.prefixo, obrigatorios=("prefixo", "placa"), tela="veiculos",
    antes_salvar=lambda o, d, a: setattr(o, "placa", (o.placa or "").upper().replace("-", "")))


# ------------------------------------------------- Módulo 2: motoristas
registrar_crud(
    bp_api, "motoristas", Motorista,
    campos={"nome": "str", "matricula": "str", "cnh": "str", "categoria_cnh": "str",
            "validade_cnh": "date", "telefone": "str", "setor": "str", "ativo": "bool"},
    ordem=Motorista.nome, obrigatorios=("nome",), tela="motoristas")

registrar_crud(
    bp_api, "fornecedores", Fornecedor,
    campos={"nome": "str", "tipo": "str", "cnpj": "str", "telefone": "str",
            "cidade": "str", "contato": "str", "ativo": "bool"},
    ordem=Fornecedor.nome, obrigatorios=("nome",), tela="fornecedores")


# ------------------------------------------------------ Módulo 3: manutenção
def _antes_os(obj, dados, anterior):
    if not obj.numero:
        obj.numero = proximo_numero_os()
    if obj.status == "Finalizada" and not obj.data_fechamento:
        obj.data_fechamento = hoje()
    if obj.status != "Finalizada":
        obj.data_fechamento = None


def _depois_os(obj, dados, anterior):
    sincronizar_status_veiculo(obj)


def _antes_excluir_os(obj):
    for item in obj.itens:
        devolver_item_os(item)
        reverter_pneu_substituido(item)  # pneu antigo volta a "Em uso"
    desvincular_movimentos(obj.id)


registrar_crud(
    bp_api, "ordens", OrdemServico,
    campos={"numero": "str", "data_abertura": "date", "data_fechamento": "date",
            "veiculo_id": "int", "motorista_id": "int", "fornecedor_id": "int",
            "mecanico": "str", "tipo": "str", "prioridade": "str", "status": "str",
            "grupo": "str", "km_veiculo": "float", "descricao": "str",
            "custo_mao_obra": "float", "custo_servicos": "float", "avaliacao": "int"},
    ordem=OrdemServico.data_abertura.desc(), obrigatorios=("veiculo_id",), tela="manutencao",
    antes_salvar=_antes_os, depois_salvar=_depois_os, antes_excluir=_antes_excluir_os,
    filtrar=_filtro_periodo(OrdemServico.data_abertura))


@bp_api.get("/ordens/<int:os_id>/itens")
@visualizar_tela("manutencao")
def listar_itens(os_id):
    ordem = db.get_or_404(OrdemServico, os_id)
    return jsonify(ordem.to_dict(com_itens=True))


@bp_api.post("/ordens/<int:os_id>/itens")
@editar_tela("manutencao")
def adicionar_item(os_id):
    ordem = db.get_or_404(OrdemServico, os_id)
    dados = request.get_json(silent=True) or {}
    item = ItemOS(ordem_servico_id=ordem.id)
    try:
        aplicar_campos(item, dados, {"peca_id": "int", "descricao": "str", "grupo": "str",
                                     "quantidade": "float", "valor_unitario": "float",
                                     "posicao_pneu": "str"})
        if item.peca_id:
            peca = db.session.get(Peca, item.peca_id)
            if not peca:
                raise ErroNegocio("Peça não encontrada.")
            item.descricao = item.descricao or peca.descricao
            item.grupo = item.grupo or peca.grupo
            if not item.valor_unitario:
                item.valor_unitario = peca.custo_unitario
        if not item.descricao:
            raise ErroNegocio("Descreva a peça ou o serviço aplicado.")
        db.session.add(item)
        db.session.flush()
        baixar_item_os(item)          # dá baixa no estoque na hora
        marcar_pneu_substituido(item)  # tira o pneu antigo daquela posição de "Em uso"
        registrar_log("criar", "itens_os", item.id, f"OS {ordem.numero}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(ordem.to_dict(com_itens=True)), 201


@bp_api.delete("/ordens/<int:os_id>/itens/<int:item_id>")
@editar_tela("manutencao")
def remover_item(os_id, item_id):
    item = db.get_or_404(ItemOS, item_id)
    ordem = db.get_or_404(OrdemServico, os_id)
    try:
        devolver_item_os(item)          # devolve ao estoque
        reverter_pneu_substituido(item)  # pneu antigo volta a "Em uso"
        db.session.delete(item)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(ordem.to_dict(com_itens=True))


# ---------------------------------------------------- Módulo 5: combustível
def _antes_abastecimento(obj, dados, anterior):
    validar_km(obj)


def _depois_abastecimento(obj, dados, anterior):
    recalcular_abastecimento(obj)


registrar_crud(
    bp_api, "abastecimentos", Abastecimento,
    campos={"data": "date", "veiculo_id": "int", "motorista_id": "int",
            "fornecedor_id": "int", "combustivel": "str", "km_atual": "float",
            "litros": "float", "valor_litro": "float", "valor_total": "float",
            "tanque_cheio": "bool"},
    ordem=Abastecimento.data.desc(), obrigatorios=("veiculo_id", "km_atual", "litros"),
    tela="combustivel",
    antes_salvar=_antes_abastecimento, depois_salvar=_depois_abastecimento,
    filtrar=_filtro_periodo(Abastecimento.data))


# ---------------------------------------------------------- Módulo 7: pneus
registrar_crud(
    bp_api, "pneus", Pneu,
    campos={"numero_fogo": "str", "veiculo_id": "int", "posicao": "str", "marca": "str",
            "medida": "str", "sulco_mm": "float", "vida": "str", "km_instalacao": "float",
            "data_instalacao": "date", "data_medicao": "date", "status": "str",
            "custo": "float"},
    ordem=Pneu.numero_fogo, obrigatorios=("numero_fogo",), tela="pneus",
    serializar=lambda o: o.to_dict(current_app.config["SULCO_MINIMO_MM"]))


# -------------------------------------------------------- Módulo 11: estoque
def _antes_peca(obj, dados, anterior):
    obj.codigo = (obj.codigo or "").strip().upper()
    if not obj.codigo:
        raise ErroNegocio("Informe o código da peça.")

    with db.session.no_autoflush:
        existente = Peca.query.filter(func.upper(Peca.codigo) == obj.codigo.upper())
        if obj.id:
            existente = existente.filter(Peca.id != obj.id)
        if existente.first():
            raise ErroNegocio(f"Já existe uma peça cadastrada com o código {obj.codigo}.")


def _depois_peca(obj, dados, anterior):
    """Saldo inicial vira um movimento de entrada — o estoque nunca muda sem histórico."""
    if anterior is None and dados.get("quantidade_inicial"):
        movimentar_estoque(obj.id, "entrada", dados["quantidade_inicial"],
                           dados.get("custo_unitario") or obj.custo_unitario,
                           documento="Saldo inicial", observacao="Cadastro da peça")


registrar_crud(
    bp_api, "pecas", Peca,
    campos={"codigo": "str", "descricao": "str", "grupo": "str", "unidade": "str",
            "estoque_minimo": "float", "custo_unitario": "float", "localizacao": "str",
            "fornecedor_id": "int", "ncm": "str", "cfop_entrada": "str",
            "cst_icms": "str", "cst_pis": "str", "cst_cofins": "str",
            "cst_ibs_cbs": "str", "classificacao_tributaria": "str"},
    ordem=Peca.descricao, obrigatorios=("codigo", "descricao"), tela="estoque",
    antes_salvar=_antes_peca, depois_salvar=_depois_peca)


# --------------------------------------- Módulo 11: notas fiscais de entrada
def _antes_salvar_nota(obj, dados, anterior):
    if anterior is not None and anterior.get("status") != "Aberta":
        raise ErroNegocio("Nota finalizada ou cancelada não pode ser editada.")


def _antes_excluir_nota(obj):
    if obj.status == "Finalizada":
        raise ErroNegocio("Estorne a nota antes de excluí-la — ela já alterou o estoque.")


registrar_crud(
    bp_api, "notas-fiscais", NotaFiscal,
    campos={"numero": "str", "serie": "str", "data_emissao": "date",
            "fornecedor_id": "int", "observacao": "str"},
    ordem=NotaFiscal.id.desc(), obrigatorios=("numero", "fornecedor_id"), tela="estoque",
    antes_salvar=_antes_salvar_nota, antes_excluir=_antes_excluir_nota)


CAMPOS_ITEM_NF = {
    "peca_id": "int", "descricao": "str", "quantidade": "float", "valor_unitario": "float",
    "ncm": "str", "cfop": "str",
    "cst_icms": "str", "base_icms": "float", "aliquota_icms": "float", "valor_icms": "float",
    "cst_pis": "str", "base_pis": "float", "aliquota_pis": "float", "valor_pis": "float",
    "cst_cofins": "str", "base_cofins": "float", "aliquota_cofins": "float", "valor_cofins": "float",
    "cst_ibs_cbs": "str", "classificacao_tributaria": "str",
    "base_ibs_cbs": "float", "aliquota_ibs": "float", "valor_ibs": "float",
    "aliquota_cbs": "float", "valor_cbs": "float",
}


def _calcular_tributo_item(item, campo_base, campo_aliquota, campo_valor):
    base = getattr(item, campo_base)
    aliquota = getattr(item, campo_aliquota)
    valor = getattr(item, campo_valor)
    subtotal = round((item.quantidade or 0) * (item.valor_unitario or 0), 2)

    if base is None and aliquota is not None:
        base = subtotal
        setattr(item, campo_base, base)
    if valor is None and base is not None and aliquota is not None:
        setattr(item, campo_valor, round(base * aliquota / 100, 2))


def _preparar_item_nf(item, peca):
    item.descricao = item.descricao or peca.descricao
    item.ncm = item.ncm or peca.ncm
    item.cfop = item.cfop or peca.cfop_entrada
    item.cst_icms = item.cst_icms or peca.cst_icms
    item.cst_pis = item.cst_pis or peca.cst_pis
    item.cst_cofins = item.cst_cofins or peca.cst_cofins
    item.cst_ibs_cbs = item.cst_ibs_cbs or peca.cst_ibs_cbs
    item.classificacao_tributaria = item.classificacao_tributaria or peca.classificacao_tributaria

    if not item.quantidade or item.quantidade <= 0:
        raise ErroNegocio("Informe uma quantidade maior que zero.")
    if item.valor_unitario is None:
        item.valor_unitario = peca.custo_unitario or 0

    numericos = (
        "valor_unitario", "base_icms", "aliquota_icms", "valor_icms",
        "base_pis", "aliquota_pis", "valor_pis",
        "base_cofins", "aliquota_cofins", "valor_cofins",
        "base_ibs_cbs", "aliquota_ibs", "valor_ibs", "aliquota_cbs", "valor_cbs",
    )
    for campo in numericos:
        valor = getattr(item, campo)
        if valor is not None and valor < 0:
            raise ErroNegocio(f"O campo {campo.replace('_', ' ')} não pode ser negativo.")

    _calcular_tributo_item(item, "base_icms", "aliquota_icms", "valor_icms")
    _calcular_tributo_item(item, "base_pis", "aliquota_pis", "valor_pis")
    _calcular_tributo_item(item, "base_cofins", "aliquota_cofins", "valor_cofins")
    _calcular_tributo_item(item, "base_ibs_cbs", "aliquota_ibs", "valor_ibs")
    _calcular_tributo_item(item, "base_ibs_cbs", "aliquota_cbs", "valor_cbs")


@bp_api.get("/notas-fiscais/<int:nota_id>/itens")
@visualizar_tela("estoque")
def listar_itens_nf(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    return jsonify(nota.to_dict(com_itens=True))


@bp_api.post("/notas-fiscais/<int:nota_id>/itens")
@editar_tela("estoque")
def adicionar_item_nf(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    dados = request.get_json(silent=True) or {}
    item = ItemNotaFiscal(nota_fiscal_id=nota.id)
    nota.itens.append(item)
    try:
        if nota.status != "Aberta":
            raise ErroNegocio("Só é possível lançar itens em uma nota aberta.")
        aplicar_campos(item, dados, CAMPOS_ITEM_NF)
        if not item.peca_id:
            raise ErroNegocio("Selecione a peça recebida.")
        peca = db.session.get(Peca, item.peca_id)
        if not peca:
            raise ErroNegocio("Peça não encontrada.")
        _preparar_item_nf(item, peca)
        db.session.add(item)
        db.session.flush()
        registrar_log("criar", "itens_nota_fiscal", item.id, f"NF {nota.numero}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True)), 201


@bp_api.put("/notas-fiscais/<int:nota_id>/itens/<int:item_id>")
@editar_tela("estoque")
def editar_item_nf(nota_id, item_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    item = db.get_or_404(ItemNotaFiscal, item_id)
    dados = request.get_json(silent=True) or {}
    try:
        if item.nota_fiscal_id != nota.id:
            raise ErroNegocio("O item não pertence a esta nota fiscal.")
        if nota.status != "Aberta":
            raise ErroNegocio("Só é possível editar itens de uma nota aberta.")
        aplicar_campos(item, dados, CAMPOS_ITEM_NF)
        if not item.peca_id:
            raise ErroNegocio("Selecione a peça recebida.")
        peca = db.session.get(Peca, item.peca_id)
        if not peca:
            raise ErroNegocio("Peça não encontrada.")
        _preparar_item_nf(item, peca)
        registrar_log("editar", "itens_nota_fiscal", item.id, f"NF {nota.numero}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True))


@bp_api.delete("/notas-fiscais/<int:nota_id>/itens/<int:item_id>")
@editar_tela("estoque")
def remover_item_nf(nota_id, item_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    item = db.get_or_404(ItemNotaFiscal, item_id)
    try:
        if item.nota_fiscal_id != nota.id:
            raise ErroNegocio("O item não pertence a esta nota fiscal.")
        if nota.status != "Aberta":
            raise ErroNegocio("Só é possível remover itens de uma nota aberta.")
        db.session.delete(item)
        registrar_log("excluir", "itens_nota_fiscal", item_id, f"NF {nota.numero}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True))


@bp_api.post("/notas-fiscais/<int:nota_id>/finalizar")
@editar_tela("estoque")
def finalizar_nf(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    try:
        finalizar_nota_fiscal(nota)
        registrar_log("editar", "notas_fiscais", nota.id, "Finalizada — estoque atualizado")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True))


@bp_api.post("/notas-fiscais/<int:nota_id>/estornar")
@editar_tela("estoque")
def estornar_nf(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    try:
        estornar_nota_fiscal(nota)
        registrar_log("editar", "notas_fiscais", nota.id, "Estornada — estoque revertido")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True))


@bp_api.get("/movimentos")
@visualizar_tela("estoque")
def listar_movimentos():
    q = MovimentoEstoque.query
    if request.args.get("peca_id"):
        q = q.filter(MovimentoEstoque.peca_id == int(request.args["peca_id"]))
    q = _filtro_periodo(MovimentoEstoque.data)(q, request.args)
    return jsonify([m.to_dict() for m in q.order_by(MovimentoEstoque.id.desc()).limit(500)])


@bp_api.post("/movimentos")
@editar_tela("estoque")
def criar_movimento():
    dados = request.get_json(silent=True) or {}
    try:
        movimentar_estoque(int(dados.get("peca_id") or 0), dados.get("tipo", "entrada"),
                           dados.get("quantidade"), dados.get("custo_unitario"),
                           documento=dados.get("documento"),
                           observacao=dados.get("observacao"))
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True}), 201


# --------------------------------------------------------- Módulo 8: orçamento
registrar_crud(
    bp_api, "orcamentos", Orcamento,
    campos={"ano": "int", "mes": "int", "categoria": "str", "veiculo_id": "int",
            "centro_custo": "str", "meta_valor": "float"},
    ordem=Orcamento.id.desc(), obrigatorios=("ano", "mes", "meta_valor"), tela="orcamento")


# ------------------------------------------- Módulos 6, 9 e 10: painéis
@bp_api.get("/painel/resumo")
@visualizar_tela("dashboard")
def painel_resumo():
    return jsonify(indicadores.resumo(request.args.get("inicio"), request.args.get("fim"),
                                      request.args.get("veiculo_id", type=int)))


@bp_api.get("/painel/graficos")
@visualizar_tela("dashboard")
def painel_graficos():
    return jsonify(indicadores.series_graficos(request.args.get("inicio"),
                                               request.args.get("fim")))


@bp_api.get("/painel/rankings")
@visualizar_tela("ranking")
def painel_rankings():
    return jsonify(indicadores.rankings(request.args.get("inicio"), request.args.get("fim")))


@bp_api.get("/painel/alertas")
@login_obrigatorio
def painel_alertas():
    return jsonify(indicadores.alertas())


# ------------------------------------------------------------- auditoria
@bp_api.get("/logs")
@perfil_obrigatorio("admin")
def listar_logs():
    """Quem criou, editou ou excluiu cada registro (500 mais recentes)."""
    q = LogAuditoria.query.order_by(LogAuditoria.id.desc())
    if request.args.get("entidade"):
        q = q.filter(LogAuditoria.entidade == request.args["entidade"])
    return jsonify([registro.to_dict() for registro in q.limit(500)])
