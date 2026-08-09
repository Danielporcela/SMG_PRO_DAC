"""Importação de planilhas, anexos e aviso por e-mail."""
import io

from flask import Blueprint, jsonify, request, send_file, session

from extensions import db
from models import Abastecimento, Anexo, ControleTarefa, OrdemServico
from services import importacao, notificacoes
from services.crud import (ErroNegocio, checar_tela, editar_tela, login_obrigatorio,
                           perfil_obrigatorio, pode_escrever, registrar_log,
                           visualizar_tela)
from services.tempo import agora

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
