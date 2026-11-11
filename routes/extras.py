"""Importação de planilhas, anexos e aviso por e-mail."""
import io

from flask import Blueprint, current_app, jsonify, request, send_file, session

from extensions import db
from models import (Abastecimento, Anexo, ControleTarefa, Fornecedor, ItemNotaFiscal,
                    NotaFiscal, NotaFiscalUniforme, OrdemCompra, OrdemServico, ParcelaNotaFiscal, ParcelaNotaFiscalUniforme, Peca)
from services import importacao, notificacoes
from services.calculos import movimentar_estoque
from services.crud import (ErroNegocio, checar_tela, editar_tela, login_obrigatorio,
                           perfil_obrigatorio, pode_escrever, registrar_log,
                           visualizar_tela)
from services.tempo import agora, hoje

bp_extras = Blueprint("extras", __name__)

# Anexos servem ordens de serviço, abastecimentos e ordens de compra; a tela
# que vale para a permissão depende de qual dos três o registro pertence.
TELA_POR_TIPO_ANEXO = {"ordens": "manutencao", "abastecimentos": "combustivel",
                       "compras": "compras"}

# Nome da coluna de dono em Anexo, por tipo — usado para filtrar/gravar.
COLUNA_POR_TIPO_ANEXO = {"ordens": "ordem_servico_id", "abastecimentos": "abastecimento_id",
                         "compras": "ordem_compra_id"}


def _tela_do_anexo(tipo):
    return TELA_POR_TIPO_ANEXO.get(tipo)


# ============================================================== importação

@bp_extras.get("/abastecimentos/modelo.xlsx")
@editar_tela("combustivel")
def baixar_modelo_abastecimentos():
    """Modelo da planilha aceita pela aba Abastecimentos."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "LANÇAMENTO"
    ws.append(["VEÍCULO", "DATA", "LITROS", "KM", "KM PERC", "KM/L"])
    ws.append([1, "2026-09-17", 90, 146889, 123, 1.37])
    ws.append([])
    ws.append(["Informe VEÍCULO como prefixo cadastrado. KM PERC e KM/L são recalculados pelo sistema."])
    fundo = PatternFill("solid", fgColor="0F3D56")
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = fundo
        c.alignment = Alignment(horizontal="center")
    for col, width in zip("ABCDEF", [14, 14, 12, 14, 14, 12]):
        ws.column_dimensions[col].width = width
    saida = io.BytesIO()
    wb.save(saida)
    saida.seek(0)
    return send_file(saida, as_attachment=True, download_name="modelo_abastecimentos.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp_extras.post("/api/abastecimentos/importar/conferir")
@editar_tela("combustivel")
def conferir_abastecimentos():
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify({"erro": "Selecione a planilha de abastecimentos."}), 400
    if not arquivo.filename.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"erro": "Envie um arquivo .xlsx ou .xlsm."}), 400
    conteudo = arquivo.read()
    return jsonify(importacao.ler_abastecimentos(io.BytesIO(conteudo)))


@bp_extras.post("/api/abastecimentos/importar/gravar")
@editar_tela("combustivel")
def gravar_abastecimentos():
    dados = request.get_json(silent=True) or {}
    linhas = dados.get("linhas") or []
    try:
        gravadas = importacao.gravar_abastecimentos(linhas)
        registrar_log("importar", "abastecimentos", 0,
                      f"{gravadas} abastecimentos por planilha")
        db.session.commit()
    except ErroNegocio:
        raise
    except Exception as e:
        # Sem isto o navegador recebia só "500" sem motivo. Agora o erro real
        # vai para o log do servidor e a tela mostra o tipo da falha.
        db.session.rollback()
        current_app.logger.exception("Falha ao gravar abastecimentos importados")
        raise ErroNegocio(
            f"Não foi possível gravar a importação ({e.__class__.__name__}). "
            "Nada foi gravado; o detalhe está no log do servidor.")
    return jsonify({"ok": True, "gravadas": gravadas})


@bp_extras.get("/importacao/modelo/<tipo>.xlsx")
@editar_tela("importacao")
def baixar_modelo(tipo):
    arquivo = importacao.gerar_modelo(tipo)
    return send_file(arquivo, as_attachment=True,
                     download_name=f"modelo_{tipo}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp_extras.post("/api/importacao/<tipo>/conferir")
@editar_tela("importacao")
def conferir_planilha(tipo):
    """Lê a planilha e devolve a prévia — ainda não grava nada."""
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"erro": "Selecione a planilha preenchida."}), 400
    if not arquivo.filename.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"erro": "Envie a planilha em .xlsx (o modelo que você baixou)."}), 400
    conteudo = arquivo.read()
    return jsonify(importacao.ler_planilha(tipo, io.BytesIO(conteudo)))


@bp_extras.post("/api/importacao/<tipo>/gravar")
@editar_tela("importacao")
def gravar_planilha(tipo):
    dados = request.get_json(silent=True) or {}
    linhas = dados.get("linhas") or []
    gravadas = importacao.gravar(tipo, linhas)
    registrar_log("importar", tipo, 0, f"{gravadas} registros por planilha")
    db.session.commit()
    return jsonify({"ok": True, "gravadas": gravadas})


# ================================================================= anexos
def _dono(tipo, registro_id):
    if tipo == "ordens":
        return db.get_or_404(OrdemServico, registro_id), {"ordem_servico_id": registro_id}
    if tipo == "abastecimentos":
        return db.get_or_404(Abastecimento, registro_id), {"abastecimento_id": registro_id}
    if tipo == "compras":
        return db.get_or_404(OrdemCompra, registro_id), {"ordem_compra_id": registro_id}
    raise ErroNegocio("Só é possível anexar em ordens de serviço, abastecimentos e ordens de compra.")


def _tipo_do_anexo(anexo):
    if anexo.ordem_servico_id:
        return "ordens"
    if anexo.abastecimento_id:
        return "abastecimentos"
    return "compras"


@bp_extras.get("/api/anexos/<tipo>/<int:registro_id>")
@login_obrigatorio
def listar_anexos(tipo, registro_id):
    erro = checar_tela(_tela_do_anexo(tipo) or tipo, "visualizar")
    if erro:
        return erro
    _dono(tipo, registro_id)
    coluna = COLUNA_POR_TIPO_ANEXO[tipo]
    anexos = Anexo.query.filter_by(**{coluna: registro_id}).order_by(Anexo.id.desc()).all()
    return jsonify([a.to_dict() for a in anexos])


@bp_extras.post("/api/anexos/<tipo>/<int:registro_id>")
@login_obrigatorio
def enviar_anexo(tipo, registro_id):
    from flask import current_app

    erro = checar_tela(_tela_do_anexo(tipo) or tipo, "editar")
    if erro:
        return erro
    _dono(tipo, registro_id)
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        return jsonify({"erro": "Escolha o arquivo que quer anexar."}), 400

    conteudo = arquivo.read()
    limite = current_app.config["TAMANHO_MAXIMO_ANEXO"]
    if len(conteudo) > limite:
        return jsonify({"erro": f"O arquivo tem {len(conteudo) / 1048576:.1f} MB. "
                                f"O limite é {limite / 1048576:.0f} MB."}), 400
    if not conteudo:
        return jsonify({"erro": "O arquivo está vazio."}), 400

    tipo_mime = (arquivo.mimetype or "").lower()
    if tipo_mime not in current_app.config["TIPOS_ANEXO"]:
        return jsonify({"erro": "Anexe uma foto (JPG, PNG, WEBP) ou um PDF."}), 400

    coluna = COLUNA_POR_TIPO_ANEXO[tipo]
    anexo = Anexo(nome=arquivo.filename[:200], tipo_mime=tipo_mime, tamanho=len(conteudo),
                  conteudo=conteudo, descricao=(request.form.get("descricao") or "")[:200] or None,
                  enviado_por=session.get("usuario_nome"), criado_em=agora(),
                  **{coluna: registro_id})
    db.session.add(anexo)
    registrar_log("anexar", tipo, registro_id, anexo.nome)
    db.session.commit()
    return jsonify(anexo.to_dict()), 201


@bp_extras.get("/api/anexos/<int:anexo_id>/arquivo")
@login_obrigatorio
def baixar_anexo(anexo_id):
    anexo = db.get_or_404(Anexo, anexo_id)
    tipo = _tipo_do_anexo(anexo)
    erro = checar_tela(_tela_do_anexo(tipo) or tipo, "visualizar")
    if erro:
        return erro
    return send_file(io.BytesIO(anexo.conteudo), mimetype=anexo.tipo_mime,
                     download_name=anexo.nome,
                     as_attachment=request.args.get("baixar") == "1")


@bp_extras.delete("/api/anexos/<int:anexo_id>")
@login_obrigatorio
def excluir_anexo(anexo_id):
    anexo = db.get_or_404(Anexo, anexo_id)
    tipo = _tipo_do_anexo(anexo)
    erro = checar_tela(_tela_do_anexo(tipo) or tipo, "editar")
    if erro:
        return erro
    registrar_log("excluir", "anexos", anexo_id, anexo.nome)
    db.session.delete(anexo)
    db.session.commit()
    return jsonify({"ok": True})


# ===================================================== notas fiscais
# Módulo 11 — lançamento de notas fiscais de entrada de peças. A nota nasce
# "Aberta": dá para lançar e remover itens à vontade, sem afetar o estoque.
# Só ao finalizar (ação explícita, irreversível) é que cada item vira uma
# entrada em MovimentoEstoque e o saldo da peça sobe — do jeito que acontece
# na prática, quando a nota chega e é conferida no almoxarifado.

def _data_nf(valor, rotulo):
    from datetime import date, datetime
    if not valor:
        return None
    if isinstance(valor, (date, datetime)):
        return valor if isinstance(valor, date) else valor.date()
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ErroNegocio(f"Data inválida em '{rotulo}'.")


def _nota_precisa_estar_aberta(nota):
    if nota.status != "Aberta":
        raise ErroNegocio("Esta nota já foi finalizada e não pode mais ser alterada.")


def _verificar_nota_duplicada(fornecedor_id, nota_id=None):
    """Bloqueia quando já existe outra nota fiscal do mesmo fornecedor
    ainda aberta (não finalizada). A nota anterior precisa ser finalizada
    (ou cancelada) antes de abrir uma nova nota para o mesmo fornecedor.
    """
    if not fornecedor_id:
        return
    conflito = NotaFiscal.query.filter(
        NotaFiscal.fornecedor_id == fornecedor_id,
        NotaFiscal.status.notin_(("Finalizada", "Cancelada")))
    if nota_id is not None:
        conflito = conflito.filter(NotaFiscal.id != nota_id)
    conflito = conflito.first()
    if conflito:
        fornecedor = db.session.get(Fornecedor, fornecedor_id)
        nome_fornecedor = fornecedor.nome if fornecedor else "este fornecedor"
        raise ErroNegocio(
            f"Já existe a nota fiscal {conflito.numero} de {nome_fornecedor} aberta "
            f"(status: {conflito.status}). Finalize-a antes de lançar uma nova nota "
            f"para o mesmo fornecedor.")


@bp_extras.get("/api/notas_fiscais")
@visualizar_tela("notas_fiscais")
def listar_notas_fiscais():
    q = NotaFiscal.query
    inicio = request.args.get("inicio")
    fim = request.args.get("fim")
    if inicio:
        q = q.filter(NotaFiscal.data_emissao >= inicio)
    if fim:
        q = q.filter(NotaFiscal.data_emissao <= fim)
    q = q.order_by(NotaFiscal.data_emissao.desc(), NotaFiscal.id.desc())
    return jsonify([n.to_dict() for n in q.all()])


@bp_extras.get("/api/notas_fiscais/<int:nota_id>")
@visualizar_tela("notas_fiscais")
def obter_nota_fiscal(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    return jsonify(nota.to_dict(com_itens=True))


@bp_extras.post("/api/notas_fiscais")
@editar_tela("notas_fiscais")
def criar_nota_fiscal():
    dados = request.get_json(silent=True) or {}
    if not dados.get("numero") or not dados.get("fornecedor_id"):
        return jsonify({"erro": "Preencha: Número, Fornecedor"}), 400
    try:
        _verificar_nota_duplicada(int(dados["fornecedor_id"]))
        nota = NotaFiscal(
            numero=str(dados["numero"]).strip(),
            serie=(dados.get("serie") or "").strip() or None,
            data_emissao=_data_nf(dados.get("data_emissao"), "Data de emissão") or hoje(),
            fornecedor_id=int(dados["fornecedor_id"]),
            observacao=(dados.get("observacao") or "").strip() or None,
        )
        db.session.add(nota)
        db.session.flush()
        registrar_log("criar", "notas_fiscais", nota.id, f"NF {nota.numero}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível salvar: {e.__class__.__name__}."}), 400
    return jsonify(nota.to_dict()), 201


@bp_extras.put("/api/notas_fiscais/<int:nota_id>")
@editar_tela("notas_fiscais")
def editar_nota_fiscal(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    dados = request.get_json(silent=True) or {}
    try:
        _nota_precisa_estar_aberta(nota)
        if dados.get("numero"):
            nota.numero = str(dados["numero"]).strip()
        if "serie" in dados:
            nota.serie = (dados.get("serie") or "").strip() or None
        if dados.get("data_emissao"):
            nota.data_emissao = _data_nf(dados["data_emissao"], "Data de emissão")
        if dados.get("fornecedor_id"):
            novo_fornecedor_id = int(dados["fornecedor_id"])
            if novo_fornecedor_id != nota.fornecedor_id:
                _verificar_nota_duplicada(novo_fornecedor_id, nota_id=nota.id)
            nota.fornecedor_id = novo_fornecedor_id
        if "observacao" in dados:
            nota.observacao = (dados.get("observacao") or "").strip() or None
        registrar_log("editar", "notas_fiscais", nota.id, f"NF {nota.numero}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível salvar: {e.__class__.__name__}."}), 400
    return jsonify(nota.to_dict())


@bp_extras.delete("/api/notas_fiscais/<int:nota_id>")
@editar_tela("notas_fiscais")
def excluir_nota_fiscal(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    try:
        _nota_precisa_estar_aberta(nota)
        registrar_log("excluir", "notas_fiscais", nota_id, f"NF {nota.numero}")
        db.session.delete(nota)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True})


@bp_extras.post("/api/notas_fiscais/<int:nota_id>/itens")
@editar_tela("notas_fiscais")
def adicionar_item_nota(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    dados = request.get_json(silent=True) or {}

    def num(campo):
        v = dados.get(campo)
        return float(str(v).replace(",", ".")) if v not in (None, "") else None

    def codigo(campo, tamanho, rotulo, padrao=None):
        """NCM, CFOP e CSTs: tira pontos/espaços (8708.30.90, 1.102) e confere
        o tamanho. O Postgres recusa texto maior que o VARCHAR da coluna (o
        SQLite local deixava passar) e isso virava 500 só em produção."""
        valor = dados.get(campo)
        if valor in (None, ""):
            valor = padrao
        valor = "".join(ch for ch in str(valor or "") if ch.isalnum())
        if len(valor) > tamanho:
            raise ErroNegocio(f"{rotulo} aceita no máximo {tamanho} caracteres "
                              f"(informado: {valor}).")
        return valor or None

    try:
        _nota_precisa_estar_aberta(nota)
        peca_id = dados.get("peca_id")
        if not peca_id:
            raise ErroNegocio("Selecione a peça.")
        peca = db.session.get(Peca, int(peca_id))
        if not peca:
            raise ErroNegocio("Peça não encontrada.")
        quantidade = float(dados.get("quantidade") or 0)
        if quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")

        item = ItemNotaFiscal(
            nota_fiscal_id=nota.id, peca_id=peca.id,
            descricao=(dados.get("descricao") or peca.descricao or "")[:160],
            quantidade=quantidade,
            valor_unitario=float(dados.get("valor_unitario") or peca.custo_unitario or 0),
            ncm=codigo("ncm", 8, "NCM", peca.ncm),
            cfop=codigo("cfop", 4, "CFOP", peca.cfop_entrada),
            cst_icms=codigo("cst_icms", 3, "CST ICMS", peca.cst_icms),
            base_icms=num("base_icms"), aliquota_icms=num("aliquota_icms"),
            valor_icms=num("valor_icms"),
            cst_pis=codigo("cst_pis", 2, "CST PIS", peca.cst_pis),
            base_pis=num("base_pis"), aliquota_pis=num("aliquota_pis"),
            valor_pis=num("valor_pis"),
            cst_cofins=codigo("cst_cofins", 2, "CST COFINS", peca.cst_cofins),
            base_cofins=num("base_cofins"), aliquota_cofins=num("aliquota_cofins"),
            valor_cofins=num("valor_cofins"),
            cst_ibs_cbs=codigo("cst_ibs_cbs", 3, "CST IBS/CBS", peca.cst_ibs_cbs),
            classificacao_tributaria=codigo("classificacao_tributaria", 6,
                                            "Classificação tributária",
                                            peca.classificacao_tributaria),
            base_ibs_cbs=num("base_ibs_cbs"),
            aliquota_ibs=num("aliquota_ibs"), valor_ibs=num("valor_ibs"),
            aliquota_cbs=num("aliquota_cbs"), valor_cbs=num("valor_cbs"),
        )
        db.session.add(item)
        registrar_log("criar", "itens_nota_fiscal", nota.id, f"NF {nota.numero}: {peca.codigo}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Falha ao lançar item na nota fiscal %s", nota_id)
        return jsonify({"erro": f"Não foi possível lançar o item ({e.__class__.__name__}). "
                                "O detalhe técnico está no log do servidor."}), 500
    return jsonify(nota.to_dict(com_itens=True)), 201


@bp_extras.delete("/api/notas_fiscais/<int:nota_id>/itens/<int:item_id>")
@editar_tela("notas_fiscais")
def remover_item_nota(nota_id, item_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    item = db.get_or_404(ItemNotaFiscal, item_id)
    try:
        _nota_precisa_estar_aberta(nota)
        db.session.delete(item)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True))


@bp_extras.post("/api/notas_fiscais/<int:nota_id>/finalizar")
@editar_tela("notas_fiscais")
def finalizar_nota_fiscal(nota_id):
    """Dá entrada no estoque de cada item e trava a nota — ação irreversível."""
    nota = db.get_or_404(NotaFiscal, nota_id)
    try:
        _nota_precisa_estar_aberta(nota)
        if not nota.itens:
            raise ErroNegocio("Lance ao menos um item antes de finalizar a nota.")
        documento = f"NF {nota.numero}" + (f"/{nota.serie}" if nota.serie else "")
        for item in nota.itens:
            if item.baixado_estoque:
                continue
            movimentar_estoque(item.peca_id, "entrada", item.quantidade,
                               item.valor_unitario, documento=documento,
                               observacao=f"Entrada pela nota fiscal #{nota.id}")
            item.baixado_estoque = True
        nota.status = "Finalizada"
        nota.data_entrada = hoje()
        registrar_log("finalizar", "notas_fiscais", nota.id, f"NF {nota.numero}")
        db.session.commit()
        resultado = nota.to_dict(com_itens=True)
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Falha ao finalizar a nota fiscal %s", nota_id)
        return jsonify({"erro": f"Não foi possível finalizar a nota ({e.__class__.__name__}). "
                                "O detalhe técnico está no log do servidor."}), 500
    return jsonify(resultado)


# ===================================================== boletos (parcelas da NF)
def _nota_aceita_parcelas(nota):
    if nota.status == "Cancelada":
        raise ErroNegocio("Esta nota está cancelada e não aceita parcelas.")


def _renumerar_parcelas(nota):
    """Mantém 1, 2, 3... na ordem de vencimento."""
    db.session.flush()
    db.session.refresh(nota)
    for n, p in enumerate(sorted(nota.parcelas, key=lambda x: (x.data_vencimento, x.id)), 1):
        p.numero = n


def _valor_positivo(valor, rotulo="Valor"):
    try:
        v = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        raise ErroNegocio(f"{rotulo} inválido.")
    if v <= 0:
        raise ErroNegocio(f"{rotulo} precisa ser maior que zero.")
    return round(v, 2)


@bp_extras.post("/api/notas_fiscais/<int:nota_id>/parcelas")
@editar_tela("notas_fiscais")
def adicionar_parcela_nota(nota_id):
    """Inclui uma data de vencimento (boleto) com o valor da parcela."""
    nota = db.get_or_404(NotaFiscal, nota_id)
    dados = request.get_json(silent=True) or {}
    try:
        _nota_aceita_parcelas(nota)
        vencimento = _data_nf(dados.get("data_vencimento"), "Vencimento")
        if not vencimento:
            raise ErroNegocio("Informe a data de vencimento.")
        valor = _valor_positivo(dados.get("valor"), "Valor da parcela")
        parcela = ParcelaNotaFiscal(nota_fiscal_id=nota.id, data_vencimento=vencimento, valor=valor)
        db.session.add(parcela)
        _renumerar_parcelas(nota)
        registrar_log("criar", "parcelas_nota_fiscal", parcela.id,
                      f"NF {nota.numero} · venc. {vencimento.isoformat()} · R$ {valor:.2f}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível salvar a parcela: {e.__class__.__name__}."}), 400
    db.session.refresh(nota)
    return jsonify(nota.to_dict(com_itens=True))


@bp_extras.post("/api/notas_fiscais/<int:nota_id>/parcelas/gerar")
@editar_tela("notas_fiscais")
def gerar_parcelas_nota(nota_id):
    """Divide o valor da nota em N parcelas com intervalo fixo de dias.

    Sem `valor_total`, usa o total dos itens lançados. O centavo que sobra
    da divisão vai para a última parcela.
    """
    from datetime import timedelta
    nota = db.get_or_404(NotaFiscal, nota_id)
    dados = request.get_json(silent=True) or {}
    try:
        _nota_aceita_parcelas(nota)
        if nota.parcelas:
            raise ErroNegocio("Esta nota já tem parcelas. Remova-as antes de gerar de novo.")
        try:
            quantidade = int(dados.get("quantidade") or 1)
            intervalo = int(dados.get("intervalo_dias") or 30)
        except (TypeError, ValueError):
            raise ErroNegocio("Quantidade de parcelas e intervalo precisam ser números inteiros.")
        if not 1 <= quantidade <= 48:
            raise ErroNegocio("A quantidade de parcelas deve ficar entre 1 e 48.")
        if not 0 <= intervalo <= 365:
            raise ErroNegocio("O intervalo deve ficar entre 0 e 365 dias.")
        primeiro = _data_nf(dados.get("primeiro_vencimento"), "Primeiro vencimento")
        if not primeiro:
            raise ErroNegocio("Informe a data do primeiro vencimento.")
        total = dados.get("valor_total")
        total = _valor_positivo(total, "Valor total") if total not in (None, "") else nota.valor_total
        if not total or total <= 0:
            raise ErroNegocio("A nota ainda não tem valor. Lance os itens antes de gerar as "
                              "parcelas ou informe o valor total.")

        base = round(total / quantidade, 2)
        for n in range(quantidade):
            valor = base if n < quantidade - 1 else round(total - base * (quantidade - 1), 2)
            db.session.add(ParcelaNotaFiscal(
                nota_fiscal_id=nota.id, numero=n + 1, valor=valor,
                data_vencimento=primeiro + timedelta(days=intervalo * n)))
        registrar_log("criar", "parcelas_nota_fiscal", nota.id,
                      f"NF {nota.numero} · {quantidade}x · R$ {total:.2f}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível gerar as parcelas: {e.__class__.__name__}."}), 400
    db.session.refresh(nota)
    return jsonify(nota.to_dict(com_itens=True))


@bp_extras.delete("/api/notas_fiscais/<int:nota_id>/parcelas/<int:parcela_id>")
@editar_tela("notas_fiscais")
def remover_parcela_nota(nota_id, parcela_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    parcela = db.session.get(ParcelaNotaFiscal, parcela_id)
    if parcela is None or parcela.nota_fiscal_id != nota.id:
        return jsonify({"erro": "Esta parcela não pertence a esta nota fiscal."}), 404
    try:
        _nota_aceita_parcelas(nota)
        db.session.delete(parcela)
        registrar_log("excluir", "parcelas_nota_fiscal", parcela_id, f"NF {nota.numero}")
        db.session.flush()
        _renumerar_parcelas(nota)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    db.session.refresh(nota)
    return jsonify(nota.to_dict(com_itens=True))


@bp_extras.post("/api/notas_fiscais/<int:nota_id>/parcelas/<int:parcela_id>/pagar")
@editar_tela("notas_fiscais")
def pagar_parcela_nota(nota_id, parcela_id):
    """Marca a parcela como paga (ou desfaz) — paga sai da lista lateral."""
    nota = db.get_or_404(NotaFiscal, nota_id)
    parcela = db.session.get(ParcelaNotaFiscal, parcela_id)
    if parcela is None or parcela.nota_fiscal_id != nota.id:
        return jsonify({"erro": "Esta parcela não pertence a esta nota fiscal."}), 404
    parcela.pago = not bool(parcela.pago)
    parcela.data_pagamento = hoje() if parcela.pago else None
    parcela.pago_por = session.get("usuario_nome", "sistema") if parcela.pago else None
    registrar_log("editar", "parcelas_nota_fiscal", parcela.id,
                  f"NF {nota.numero} · parcela {parcela.numero} · pago={parcela.pago}")
    db.session.commit()
    db.session.refresh(nota)
    return jsonify(nota.to_dict(com_itens=True))


@bp_extras.get("/api/parcelas_nota/a_vencer")
@visualizar_tela("estoque")
def parcelas_a_vencer():
    """Alimenta o painel lateral "Boletos a vencer".

    Por período (é o que o painel usa): `inicio` e `fim` (AAAA-MM-DD) trazem
    todas as parcelas não pagas com vencimento dentro do intervalo, da mais
    antiga para a mais nova. Com `vencidas=1`, entram também as que já venceram
    antes do início do período e continuam sem pagamento.

    Por data única (compatibilidade): `data` (padrão: hoje) e `modo`:
      - "ate": vencimento até a data (inclui vencidas);
      - "na":  só as que vencem exatamente na data.
    """
    try:
        inicio = _data_nf(request.args.get("inicio"), "Data inicial")
        fim = _data_nf(request.args.get("fim"), "Data final")
        data = _data_nf(request.args.get("data"), "Data")
    except ErroNegocio as e:
        return jsonify({"erro": str(e)}), 400

    base = hoje()
    q = (ParcelaNotaFiscal.query.join(NotaFiscal)
         .filter(ParcelaNotaFiscal.pago.is_(False), NotaFiscal.status != "Cancelada"))

    if inicio or fim:
        if inicio and fim and inicio > fim:
            return jsonify({"erro": "A data inicial não pode ser maior que a data final."}), 400
        incluir_vencidas = request.args.get("vencidas") in ("1", "true", "on")
        if fim:
            q = q.filter(ParcelaNotaFiscal.data_vencimento <= fim)
        if inicio:
            if incluir_vencidas:
                q = q.filter(db.or_(ParcelaNotaFiscal.data_vencimento >= inicio,
                                    ParcelaNotaFiscal.data_vencimento < base))
            else:
                q = q.filter(ParcelaNotaFiscal.data_vencimento >= inicio)
        modo = "periodo"
    else:
        data = data or base
        modo = "na" if request.args.get("modo") == "na" else "ate"
        q = q.filter(ParcelaNotaFiscal.data_vencimento == data) if modo == "na" \
            else q.filter(ParcelaNotaFiscal.data_vencimento <= data)

    # Totais sobre tudo que casa com o filtro; a lista é limitada só para não pesar a tela.
    limite = 500
    total_parcelas = q.count()
    parcelas = q.order_by(ParcelaNotaFiscal.data_vencimento, ParcelaNotaFiscal.id).limit(limite).all()
    soma = (q.with_entities(db.func.coalesce(db.func.sum(ParcelaNotaFiscal.valor), 0)).scalar()) or 0

    itens = []
    for p in parcelas:
        d = p.to_dict()
        d["dias"] = (p.data_vencimento - base).days
        d["vencida"] = p.data_vencimento < base
        itens.append(d)
    # Boletos das notas de uniformes compartilham a mesma tela e os mesmos filtros.
    qu = (ParcelaNotaFiscalUniforme.query.join(NotaFiscalUniforme)
          .filter(ParcelaNotaFiscalUniforme.pago.is_(False), NotaFiscalUniforme.status != "Cancelada"))
    if inicio or fim:
        if fim:
            qu = qu.filter(ParcelaNotaFiscalUniforme.data_vencimento <= fim)
        if inicio:
            if incluir_vencidas:
                qu = qu.filter(db.or_(ParcelaNotaFiscalUniforme.data_vencimento >= inicio,
                                      ParcelaNotaFiscalUniforme.data_vencimento < base))
            else:
                qu = qu.filter(ParcelaNotaFiscalUniforme.data_vencimento >= inicio)
    else:
        qu = qu.filter(ParcelaNotaFiscalUniforme.data_vencimento == data) if modo == "na" \
             else qu.filter(ParcelaNotaFiscalUniforme.data_vencimento <= data)
    parcelas_uniformes = qu.order_by(ParcelaNotaFiscalUniforme.data_vencimento,
                                     ParcelaNotaFiscalUniforme.id).all()
    itens_uniformes = []
    for parcela in parcelas_uniformes:
        d = parcela.to_dict()
        d["dias"] = (parcela.data_vencimento - base).days
        d["vencida"] = parcela.data_vencimento < base
        itens_uniformes.append(d)
    itens.extend(itens_uniformes)
    itens.sort(key=lambda x: (x.get("data_vencimento") or "", x.get("id") or 0))
    total_parcelas += len(itens_uniformes)
    soma += sum(float(x.get("valor") or 0) for x in itens_uniformes)

    return jsonify({
        "modo": modo,
        "inicio": inicio.isoformat() if inicio else None,
        "fim": fim.isoformat() if fim else None,
        "data": data.isoformat() if data else None,
        "qtd": total_parcelas,
        "exibidas": len(itens),
        "total": round(float(soma), 2),
        "itens": itens,
    })


# ========================================================== notificações
@bp_extras.get("/api/notificacoes/situacao")
@perfil_obrigatorio("admin")
def situacao_email():
    from flask import current_app

    registro = ControleTarefa.query.filter_by(tarefa=notificacoes.TAREFA_DIARIA).first()
    return jsonify({
        "configurado": notificacoes.configurado(),
        "ativo": current_app.config.get("ALERTAS_EMAIL_ATIVO"),
        "servidor": f"{current_app.config['SMTP_HOST']}:{current_app.config['SMTP_PORTA']}",
        "remetente": current_app.config.get("EMAIL_REMETENTE"),
        "destinatarios": notificacoes.destinatarios_padrao(),
        "hora_envio": current_app.config.get("ALERTAS_HORA"),
        "ultima_execucao": registro.ultima_execucao.isoformat()
        if registro and registro.ultima_execucao else None,
        "ultimo_resultado": registro.ultimo_resultado if registro else None,
    })


@bp_extras.post("/api/notificacoes/testar")
@perfil_obrigatorio("admin")
def testar_email():
    """Envia uma mensagem de teste para conferir a configuração."""
    dados = request.get_json(silent=True) or {}
    para = [e.strip() for e in (dados.get("destinatario") or "").split(",") if e.strip()]
    corpo = notificacoes.montar_resumo([
        {"nivel": "info", "categoria": "Teste", "titulo": "Envio de e-mail funcionando",
         "detalhe": "Se você recebeu esta mensagem, os avisos automáticos estão prontos."}])
    enviados = notificacoes.enviar_email("[SGMF] Teste de envio", corpo, para or None)
    registrar_log("testar", "email", 0, ", ".join(enviados))
    db.session.commit()
    return jsonify({"ok": True, "destinatarios": enviados})


@bp_extras.post("/api/notificacoes/enviar-agora")
@perfil_obrigatorio("admin")
def enviar_resumo_agora():
    return jsonify(notificacoes.executar_alertas_diarios(forcar=True))


@bp_extras.get("/tarefas/alertas-diarios")
def tarefa_alertas():
    """URL para um agendador externo, caso o disparo interno seja desligado."""
    from flask import current_app

    chave = current_app.config.get("CHAVE_TAREFAS")
    if not chave or request.args.get("chave") != chave:
        return jsonify({"erro": "Chave inválida."}), 403
    return jsonify(notificacoes.executar_alertas_diarios())
