"""Importação de planilhas, anexos e aviso por e-mail."""
import io

from flask import Blueprint, jsonify, request, send_file, session

from extensions import db
from models import (Abastecimento, Anexo, ControleTarefa, ItemNotaFiscal, NotaFiscal,
                    OrdemServico, Peca)
from services import importacao, notificacoes
from services.calculos import movimentar_estoque
from services.crud import (ErroNegocio, checar_tela, editar_tela, login_obrigatorio,
                           perfil_obrigatorio, pode_escrever, registrar_log,
                           visualizar_tela)
from services.tempo import agora, hoje

bp_extras = Blueprint("extras", __name__)

# Anexos servem tanto ordens de serviço quanto abastecimentos; a tela que
# vale para a permissão depende de qual dos dois o registro pertence.
TELA_POR_TIPO_ANEXO = {"ordens": "manutencao", "abastecimentos": "combustivel"}


def _tela_do_anexo(tipo):
    return TELA_POR_TIPO_ANEXO.get(tipo)


# ============================================================== importação
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
    return jsonify(importacao.ler_planilha(tipo, arquivo.stream))


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
    raise ErroNegocio("Só é possível anexar em ordens de serviço e abastecimentos.")


@bp_extras.get("/api/anexos/<tipo>/<int:registro_id>")
@login_obrigatorio
def listar_anexos(tipo, registro_id):
    erro = checar_tela(_tela_do_anexo(tipo) or tipo, "visualizar")
    if erro:
        return erro
    _dono(tipo, registro_id)
    coluna = "ordem_servico_id" if tipo == "ordens" else "abastecimento_id"
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

    coluna = "ordem_servico_id" if tipo == "ordens" else "abastecimento_id"
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
    tipo = "ordens" if anexo.ordem_servico_id else "abastecimentos"
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
    tipo = "ordens" if anexo.ordem_servico_id else "abastecimentos"
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


@bp_extras.get("/api/notas_fiscais")
@visualizar_tela("estoque")
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
@visualizar_tela("estoque")
def obter_nota_fiscal(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    return jsonify(nota.to_dict(com_itens=True))


@bp_extras.post("/api/notas_fiscais")
@editar_tela("estoque")
def criar_nota_fiscal():
    dados = request.get_json(silent=True) or {}
    if not dados.get("numero") or not dados.get("fornecedor_id"):
        return jsonify({"erro": "Preencha: Número, Fornecedor"}), 400
    try:
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
@editar_tela("estoque")
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
            nota.fornecedor_id = int(dados["fornecedor_id"])
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
@editar_tela("estoque")
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
@editar_tela("estoque")
def adicionar_item_nota(nota_id):
    nota = db.get_or_404(NotaFiscal, nota_id)
    dados = request.get_json(silent=True) or {}

    def num(campo):
        v = dados.get(campo)
        return float(v) if v not in (None, "") else None

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
            descricao=(dados.get("descricao") or peca.descricao),
            quantidade=quantidade,
            valor_unitario=float(dados.get("valor_unitario") or peca.custo_unitario or 0),
            ncm=(dados.get("ncm") or peca.ncm),
            cfop=(dados.get("cfop") or peca.cfop_entrada),
            cst_icms=(dados.get("cst_icms") or peca.cst_icms),
            base_icms=num("base_icms"), aliquota_icms=num("aliquota_icms"),
            valor_icms=num("valor_icms"),
            cst_pis=(dados.get("cst_pis") or peca.cst_pis),
            base_pis=num("base_pis"), aliquota_pis=num("aliquota_pis"),
            valor_pis=num("valor_pis"),
            cst_cofins=(dados.get("cst_cofins") or peca.cst_cofins),
            base_cofins=num("base_cofins"), aliquota_cofins=num("aliquota_cofins"),
            valor_cofins=num("valor_cofins"),
            cst_ibs_cbs=(dados.get("cst_ibs_cbs") or peca.cst_ibs_cbs),
            classificacao_tributaria=(dados.get("classificacao_tributaria")
                                      or peca.classificacao_tributaria),
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
    return jsonify(nota.to_dict(com_itens=True)), 201


@bp_extras.delete("/api/notas_fiscais/<int:nota_id>/itens/<int:item_id>")
@editar_tela("estoque")
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
@editar_tela("estoque")
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
            movimentar_estoque(item.peca_id, "entrada", item.quantidade, item.valor_unitario,
                               documento=documento, observacao=f"Nota fiscal #{nota.id}")
            item.baixado_estoque = True
        nota.status = "Finalizada"
        nota.data_entrada = hoje()
        registrar_log("finalizar", "notas_fiscais", nota.id, f"NF {nota.numero}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível finalizar: {e.__class__.__name__}."}), 400
    return jsonify(nota.to_dict(com_itens=True))


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
