"""API REST dos módulos: frota, manutenção, combustível, pneus, estoque e orçamento."""
from datetime import date

from flask import Blueprint, current_app, jsonify, request

from extensions import db
from models import (Abastecimento, Fornecedor, ItemOS, ItemOSPecaSerial, LogAuditoria,
                    Motorista, MovimentoEstoque, Orcamento, OrdemServico, Peca, PecaSerial,
                    Pneu, ServicoTerceiro, Veiculo, proximo_codigo_peca)
from services import indicadores
from services.calculos import (baixar_item_os, dar_entrada_serial, desvincular_movimentos,
                               devolver_item_os, devolver_serial_ao_estoque,
                               instalar_serial_no_item, movimentar_estoque,
                               proximo_numero_os, recalcular_abastecimento,
                               regularizar_seriais_peca, sincronizar_status_veiculo,
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


# ---------------------------------------- Lançamento financeiro: serviço terceiro
def _validar_servico_terceiro(obj, dados, anterior):
    if not obj.veiculo_id or not db.session.get(Veiculo, obj.veiculo_id):
        raise ErroNegocio("Selecione um veículo válido.")
    if not (obj.prestador or "").strip():
        raise ErroNegocio("Informe o prestador/empresa do serviço.")
    if not (obj.descricao or "").strip():
        raise ErroNegocio("Descreva o serviço executado.")
    if (obj.valor or 0) <= 0:
        raise ErroNegocio("Informe um valor maior que zero para o serviço.")
    if obj.ordem_servico_id:
        ordem = db.session.get(OrdemServico, obj.ordem_servico_id)
        if not ordem:
            raise ErroNegocio("A OS informada não existe.")
        if ordem.veiculo_id != obj.veiculo_id:
            raise ErroNegocio("A OS selecionada pertence a outro veículo.")


def _filtrar_servicos_terceiros(q, args):
    q = _filtro_periodo(ServicoTerceiro.data)(q, args)
    veiculo_id = args.get("veiculo_id", type=int)
    if veiculo_id:
        q = q.filter(ServicoTerceiro.veiculo_id == veiculo_id)
    return q


registrar_crud(
    bp_api, "servicos-terceiros", ServicoTerceiro,
    campos={"data": "date", "veiculo_id": "int", "ordem_servico_id": "int",
            "prestador": "str", "tipo_servico": "str", "descricao": "str",
            "valor": "float", "documento": "str", "observacao": "str"},
    ordem=ServicoTerceiro.data.desc(),
    obrigatorios=("data", "veiculo_id", "prestador", "descricao", "valor"),
    tela="manutencao", antes_salvar=_validar_servico_terceiro,
    filtrar=_filtrar_servicos_terceiros)


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
    desvincular_movimentos(obj.id)


registrar_crud(
    bp_api, "ordens", OrdemServico,
    campos={"numero": "str", "data_abertura": "date", "data_fechamento": "date",
            "veiculo_id": "int", "motorista_id": "int", "fornecedor_id": "int",
            "mecanico": "str", "tipo": "str", "prioridade": "str", "status": "str",
            "grupo": "str", "hora_inicio": "time", "hora_fim": "time",
            "km_veiculo": "float", "descricao": "str",
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
                                     "quantidade": "float", "valor_unitario": "float"})
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
        # Quando o item tem peça vinculada, a baixa do estoque só acontece
        # ao informar o(s) número(s) de série de cada unidade instalada —
        # ver /ordens/<id>/itens/<id>/vincular-serial logo abaixo. Itens
        # antigos sem nenhuma unidade cadastrada continuam pelo fluxo por
        # quantidade (compatibilidade).
        if not item.peca_id:
            baixar_item_os(item)
        registrar_log("criar", "itens_os", item.id, f"OS {ordem.numero}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(ordem.to_dict(com_itens=True)), 201


@bp_api.post("/ordens/<int:os_id>/itens/<int:item_id>/vincular-serial")
@editar_tela("manutencao")
def vincular_serial_item(os_id, item_id):
    """Aplica UMA unidade específica (número de série) a um item da OS.

    Chamada uma vez por unidade — um item com quantidade 3 precisa de 3
    chamadas, uma por número de série instalado.
    """
    ordem = db.get_or_404(OrdemServico, os_id)
    item = db.get_or_404(ItemOS, item_id)
    dados = request.get_json(silent=True) or {}
    try:
        if item.ordem_servico_id != ordem.id:
            raise ErroNegocio("Este item não pertence a esta ordem de serviço.")
        if len(item.pecas_serial) >= (item.quantidade or 0):
            raise ErroNegocio("Este item já tem todas as unidades vinculadas.")
        serial = instalar_serial_no_item(dados.get("numero_serie"), item, ordem)
        registrar_log("vincular", "itens_os_pecas_serial", item.id,
                      f"OS {ordem.numero}: {serial.numero_serie}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(ordem.to_dict(com_itens=True)), 201


@bp_api.delete("/ordens/<int:os_id>/itens/<int:item_id>/vincular-serial/<int:vinculo_id>")
@editar_tela("manutencao")
def desvincular_serial_item(os_id, item_id, vinculo_id):
    """Remove uma unidade específica do item (sem excluir o item inteiro) —
    a peça volta para o estoque e pode ser reinstalada depois."""
    ordem = db.get_or_404(OrdemServico, os_id)
    vinculo = db.get_or_404(ItemOSPecaSerial, vinculo_id)
    try:
        if vinculo.item_os_id != item_id:
            raise ErroNegocio("Vínculo não encontrado neste item.")
        devolver_serial_ao_estoque(vinculo.peca_serial, motivo="Removida da OS")
        db.session.delete(vinculo)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(ordem.to_dict(com_itens=True))


@bp_api.get("/pecas/<int:peca_id>/seriais-estoque")
@visualizar_tela("manutencao")
def listar_seriais_em_estoque(peca_id):
    """Unidades dessa peça disponíveis para instalar (status 'Estoque') —
    alimenta o seletor da tela de Ordens de serviço."""
    seriais = (PecaSerial.query
              .filter_by(peca_id=peca_id, status="Estoque")
              .order_by(PecaSerial.numero_serie).all())
    return jsonify([s.to_dict() for s in seriais])


@bp_api.get("/pecas/<int:peca_id>/rastreio")
@visualizar_tela("estoque")
def listar_rastreio_peca(peca_id):
    """Todas as unidades (qualquer status) dessa peça, com o histórico
    completo de cada uma — alimenta o botão "Rastrear" da tela de Estoque.
    """
    peca = db.get_or_404(Peca, peca_id)
    seriais = (PecaSerial.query
              .filter_by(peca_id=peca_id)
              .order_by(PecaSerial.numero_serie).all())
    resultados = []
    for serial in seriais:
        dado = serial.to_dict()
        dado["historico"] = [m.to_dict() for m in serial.movimentos]
        resultados.append(dado)
    return jsonify({"peca_id": peca.id, "peca_codigo": peca.codigo,
                    "peca_descricao": peca.descricao,
                    "total": len(resultados), "resultados": resultados})


@bp_api.get("/pecas/<int:peca_id>/regularizacao")
@visualizar_tela("estoque")
def situacao_regularizacao(peca_id):
    """Diz quantas unidades dessa peça ainda não têm número de série —
    saldo lançado antes deste recurso existir."""
    peca = db.get_or_404(Peca, peca_id)
    ja_regularizadas = PecaSerial.query.filter_by(peca_id=peca_id).count()
    pendente = max(0, int(round((peca.quantidade or 0))) - ja_regularizadas)
    return jsonify({"peca_id": peca.id, "quantidade": peca.quantidade,
                    "regularizadas": ja_regularizadas, "pendente": pendente})


@bp_api.post("/pecas/<int:peca_id>/regularizacao")
@editar_tela("estoque")
def regularizar_peca(peca_id):
    """Converte o saldo antigo (peça lançada antes do rastreio por série)
    em unidades individuais, com um número de série por unidade."""
    dados = request.get_json(silent=True) or {}
    brutos = str(dados.get("numeros_serie") or "").replace(",", "\n").splitlines()
    numeros = [n.strip() for n in brutos if n.strip()]
    try:
        criados = regularizar_seriais_peca(peca_id, numeros)
        registrar_log("regularizar", "pecas_serial", peca_id, f"{len(criados)} unidade(s)")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True, "criados": [c.to_dict() for c in criados]}), 201


@bp_api.delete("/ordens/<int:os_id>/itens/<int:item_id>")
@editar_tela("manutencao")
def remover_item(os_id, item_id):
    item = db.get_or_404(ItemOS, item_id)
    ordem = db.get_or_404(OrdemServico, os_id)
    try:
        devolver_item_os(item)        # devolve ao estoque (todas as unidades vinculadas)
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
    """Peça nova: o Código é sempre gerado pelo sistema (0001, 0002...),
    ignorando qualquer valor enviado pela tela — o campo fica travado lá.
    Em edição, o código não muda.
    """
    if anterior is None:
        obj.codigo = proximo_codigo_peca()


def _depois_peca(obj, dados, anterior):
    """Saldo inicial vira uma unidade rastreável por número de série — o
    estoque nunca muda sem histórico, e agora nenhuma peça entra sem um
    número de série/identificação vinculado.
    """
    if anterior is not None or not dados.get("quantidade_inicial"):
        return
    quantidade = float(dados["quantidade_inicial"])
    brutos = str(dados.get("numeros_serie") or "").replace(",", "\n").splitlines()
    numeros = [n.strip() for n in brutos if n.strip()]
    if len(numeros) != int(quantidade):
        raise ErroNegocio(
            f"Informe {int(quantidade)} número(s) de série (um por linha) — "
            f"a quantidade de números precisa bater com o saldo inicial informado.")
    for numero in numeros:
        dar_entrada_serial(obj.id, numero, dados.get("custo_unitario") or obj.custo_unitario,
                           origem="Cadastro manual", documento="Saldo inicial",
                           observacao="Cadastro da peça")


registrar_crud(
    bp_api, "pecas", Peca,
    campos={"codigo": "str", "referencia": "str", "descricao": "str", "grupo": "str",
            "unidade": "str", "estoque_minimo": "float", "custo_unitario": "float",
            "localizacao": "str", "fornecedor_id": "int"},
    ordem=Peca.codigo, obrigatorios=("descricao",), tela="estoque",
    antes_salvar=_antes_peca, depois_salvar=_depois_peca)


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


# ------------------------------------------- Lista de mecânicos das OS
@bp_api.get("/mecanicos-os")
@login_obrigatorio
def listar_mecanicos_os():
    """Retorna os nomes únicos de mecânicos já cadastrados nas OS,
    normalizados (sem duplicatas por capitalização), para popular o datalist."""
    from sqlalchemy import func
    nomes = (
        db.session.query(OrdemServico.mecanico)
        .filter(OrdemServico.mecanico.isnot(None),
                OrdemServico.mecanico != "")
        .distinct()
        .order_by(func.lower(OrdemServico.mecanico))
        .all()
    )
    # Deduplica por nome em maiúsculas (ex: "cleiton" e "CLEITON" viram um só)
    vistos = {}
    for (nome,) in nomes:
        chave = nome.strip().upper()
        if chave not in vistos:
            vistos[chave] = nome.strip().title()
    return jsonify(sorted(vistos.values()))


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
