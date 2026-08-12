"""Envio e agendamento das notificações do SGMF Pro."""
from __future__ import annotations

import smtplib
import threading
import time
from html import escape
from email.message import EmailMessage

from flask import current_app

from extensions import db
from models import ControleTarefa
from services.alertas import (concluir_notificacao, listar_alertas_ativos,
                              reservar_eventos_notificacao, sincronizar_estados)
from services.tempo import agora, hoje


def _destinatarios():
    bruto = current_app.config.get("EMAIL_DESTINATARIOS", "") or ""
    for sep in (";", "\n"):
        bruto = bruto.replace(sep, ",")
    return [item.strip() for item in bruto.split(",") if item.strip()]


def email_configurado():
    return bool(
        current_app.config.get("ALERTAS_EMAIL_ATIVO")
        and current_app.config.get("SMTP_HOST")
        and current_app.config.get("SMTP_USUARIO")
        and current_app.config.get("SMTP_SENHA")
        and _destinatarios()
    )


def enviar_email(assunto, corpo_texto, corpo_html=None):
    if not email_configurado():
        return False, "E mail não enviado porque o SMTP não está completamente configurado."

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = current_app.config.get("EMAIL_REMETENTE") or current_app.config.get("SMTP_USUARIO")
    msg["To"] = ", ".join(_destinatarios())
    msg.set_content(corpo_texto)
    if corpo_html:
        msg.add_alternative(corpo_html, subtype="html")

    host = current_app.config.get("SMTP_HOST")
    porta = int(current_app.config.get("SMTP_PORTA", 587))
    usuario = current_app.config.get("SMTP_USUARIO")
    senha = current_app.config.get("SMTP_SENHA")
    usar_ssl = bool(current_app.config.get("SMTP_SSL"))
    usar_tls = bool(current_app.config.get("SMTP_TLS"))

    cliente_cls = smtplib.SMTP_SSL if usar_ssl else smtplib.SMTP
    with cliente_cls(host, porta, timeout=30) as smtp:
        if not usar_ssl:
            smtp.ehlo()
            if usar_tls:
                smtp.starttls()
                smtp.ehlo()
        smtp.login(usuario, senha)
        smtp.send_message(msg)
    return True, "E mail enviado."


def _texto_eventos(eventos):
    linhas = ["SGMF Pro", ""]
    for e in eventos:
        if e["status"] == "sanado":
            linhas.append(f"SANADO: {e.get('titulo') or 'Alerta'}")
        else:
            linhas.append(f"NOVO ALERTA: {e.get('titulo') or 'Alerta'}")
    linhas.extend(["", "Consulte o sistema para os detalhes atualizados."])
    return "\n".join(linhas)


def _html_eventos(eventos):
    itens = []
    for e in eventos:
        rotulo = "SANADO" if e["status"] == "sanado" else "NOVO ALERTA"
        titulo = escape(str(e.get('titulo') or 'Alerta'))
        itens.append(f"<li><strong>{rotulo}</strong>: {titulo}</li>")
    return "<h2>SGMF Pro</h2><ul>" + "".join(itens) + "</ul><p>Consulte o sistema para os detalhes atualizados.</p>"


def enviar_mudancas_alertas():
    sincronizar_estados()
    eventos = reservar_eventos_notificacao()
    if not eventos:
        return {"enviados": 0, "motivo": "Sem mudanças de estado."}

    if not current_app.config.get("ALERTAS_MUDANCA_EMAIL_ATIVO", True):
        concluir_notificacao(eventos, sucesso=True)
        return {"enviados": 0, "motivo": "Avisos de mudança estão desativados."}

    if not current_app.config.get("ALERTAS_SANADO_EMAIL_ATIVO", True):
        permitidos = [e for e in eventos if e["status"] != "sanado"]
        ignorados = [e for e in eventos if e["status"] == "sanado"]
        concluir_notificacao(ignorados, sucesso=True)
        eventos = permitidos
        if not eventos:
            return {"enviados": 0, "motivo": "Somente alertas sanados estavam pendentes."}

    if not email_configurado():
        concluir_notificacao(eventos, sucesso=False)
        return {"enviados": 0, "motivo": "SMTP não configurado."}

    novos = sum(1 for e in eventos if e["status"] == "ativo")
    sanados = sum(1 for e in eventos if e["status"] == "sanado")
    assunto = f"SGMF Pro | {novos} novo(s) | {sanados} sanado(s)"
    try:
        ok, detalhe = enviar_email(assunto, _texto_eventos(eventos), _html_eventos(eventos))
        concluir_notificacao(eventos, sucesso=ok)
        return {"enviados": len(eventos) if ok else 0, "motivo": detalhe}
    except Exception as exc:
        db.session.rollback()
        concluir_notificacao(eventos, sucesso=False)
        return {"enviados": 0, "motivo": str(exc)}


def _controle_diario():
    tarefa = "email_alertas_diario"
    registro = ControleTarefa.query.filter_by(tarefa=tarefa).first()
    if registro is None:
        registro = ControleTarefa(tarefa=tarefa)
        db.session.add(registro)
        db.session.flush()
    return registro


def enviar_resumo_diario(forcar=False):
    if not email_configurado():
        return {"enviado": False, "motivo": "SMTP não configurado."}
    registro = _controle_diario()
    data = hoje()
    hora = int(current_app.config.get("ALERTAS_HORA", 7))
    if not forcar:
        if agora().hour < hora:
            db.session.rollback()
            return {"enviado": False, "motivo": "Ainda não chegou o horário do resumo."}
        if registro.ultima_execucao == data:
            db.session.rollback()
            return {"enviado": False, "motivo": "Resumo já enviado hoje."}

    ativos = listar_alertas_ativos()
    if ativos:
        linhas = ["SGMF Pro", "", f"Alertas ativos: {len(ativos)}", ""]
        for a in ativos:
            linhas.append(f"{a['severidade'].upper()}: {a['titulo']} | {a['mensagem']}")
        assunto = f"SGMF Pro | Resumo diário | {len(ativos)} alerta(s) ativo(s)"
    else:
        linhas = ["SGMF Pro", "", "Não há alertas ativos no momento."]
        assunto = "SGMF Pro | Resumo diário | Sem alertas ativos"

    try:
        ok, detalhe = enviar_email(assunto, "\n".join(linhas))
        if ok:
            registro.ultima_execucao = data
            registro.ultimo_resultado = f"{len(ativos)} alerta(s) ativo(s)"
            registro.atualizado_em = agora()
            db.session.commit()
        return {"enviado": ok, "motivo": detalhe}
    except Exception as exc:
        db.session.rollback()
        return {"enviado": False, "motivo": str(exc)}


def processar_alertas(forcar_resumo=False):
    mudancas = enviar_mudancas_alertas()
    resumo = enviar_resumo_diario(forcar=forcar_resumo)
    return {"mudancas": mudancas, "resumo": resumo}


def iniciar_agendador(app):
    """Inicia um ciclo leve que reconcilia alertas e envia notificações."""
    if getattr(app, "_sgmf_agendador_alertas", False):
        return
    app._sgmf_agendador_alertas = True

    intervalo = max(int(app.config.get("INTERVALO_AGENDADOR", 600)), 60)

    def ciclo():
        while True:
            try:
                with app.app_context():
                    resultado = processar_alertas()
                    app.logger.info("Ciclo de alertas: %s", resultado)
            except Exception:
                app.logger.exception("Falha no ciclo de alertas")
                try:
                    with app.app_context():
                        db.session.rollback()
                except Exception:
                    pass
            time.sleep(intervalo)

    thread = threading.Thread(target=ciclo, name="sgmf-alertas", daemon=True)
    thread.start()


# Compatibilidade com chamadas usadas por versões anteriores.
enviar_alertas = enviar_mudancas_alertas
enviar_alertas_email = enviar_mudancas_alertas
disparar_alertas = processar_alertas
