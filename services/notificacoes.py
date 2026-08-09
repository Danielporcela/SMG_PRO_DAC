"""Aviso por e-mail dos alertas críticos.

Vem desligado: sem a senha do SMTP configurada, o sistema não tenta enviar
nada e apenas informa que o envio está inativo. Para ligar, preencha
SMTP_SENHA (no Gmail, uma "senha de aplicativo") — sem mexer em código.
"""
import smtplib
import threading
import time
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app
from sqlalchemy import text

from extensions import db
from models import ControleTarefa
from services.crud import ErroNegocio
from services.tempo import agora, hoje

TAREFA_DIARIA = "alertas_diarios"


def configurado():
    cfg = current_app.config
    return bool(cfg.get("SMTP_HOST") and cfg.get("SMTP_USUARIO") and cfg.get("SMTP_SENHA"))


def destinatarios_padrao():
    bruto = current_app.config.get("EMAIL_DESTINATARIOS") or ""
    return [e.strip() for e in bruto.replace(";", ",").split(",") if e.strip()]


def enviar_email(assunto, corpo_html, destinatarios=None):
    """Envia um e-mail. Levanta ErroNegocio com motivo claro se não der."""
    cfg = current_app.config
    if not configurado():
        raise ErroNegocio("O envio de e-mail ainda não foi configurado. "
                          "Preencha SMTP_SENHA nas variáveis de ambiente.")

    para = destinatarios or destinatarios_padrao()
    if not para:
        raise ErroNegocio("Nenhum destinatário configurado em EMAIL_DESTINATARIOS.")

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = formataddr(("SGMF Pro", cfg.get("EMAIL_REMETENTE") or cfg["SMTP_USUARIO"]))
    mensagem["To"] = ", ".join(para)
    mensagem.set_content("Este aviso do SGMF Pro precisa de um leitor de e-mail "
                         "que exiba HTML.")
    mensagem.add_alternative(corpo_html, subtype="html")

    try:
        if cfg.get("SMTP_SSL"):
            servidor = smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORTA"], timeout=20)
        else:
            servidor = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORTA"], timeout=20)
        with servidor:
            if cfg.get("SMTP_TLS") and not cfg.get("SMTP_SSL"):
                servidor.starttls()
            servidor.login(cfg["SMTP_USUARIO"], cfg["SMTP_SENHA"])
            servidor.send_message(mensagem)
    except smtplib.SMTPAuthenticationError:
        raise ErroNegocio("O servidor recusou usuário ou senha. No Gmail é preciso usar "
                          "uma senha de aplicativo, não a senha normal da conta.")
    except (smtplib.SMTPException, OSError) as e:
        raise ErroNegocio(f"Não consegui falar com o servidor de e-mail ({e.__class__.__name__}). "
                          f"Confira SMTP_HOST e SMTP_PORTA.")
    return para


# ----------------------------------------------------------------- conteúdo
CORES = {"critico": "#C4451D", "atencao": "#F5A800", "info": "#0F3D56"}


def montar_resumo(alertas):
    data = agora().strftime("%d/%m/%Y")
    criticos = [a for a in alertas if a["nivel"] == "critico"]
    atencao = [a for a in alertas if a["nivel"] == "atencao"]

    def bloco(titulo, itens):
        if not itens:
            return ""
        linhas = "".join(
            f'<tr><td style="padding:8px 12px;border-left:4px solid {CORES[a["nivel"]]};'
            f'border-bottom:1px solid #E4E9ED">'
            f'<div style="font-weight:600;color:#16202B">{a["titulo"]}</div>'
            f'<div style="font-size:13px;color:#5F7080">{a["detalhe"]}</div></td></tr>'
            for a in itens)
        return (f'<h3 style="font-family:Arial;font-size:15px;color:#0F3D56;'
                f'margin:22px 0 8px">{titulo}</h3>'
                f'<table style="width:100%;border-collapse:collapse">{linhas}</table>')

    corpo = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#16202B">
      <div style="background:#0E141B;padding:18px 22px;border-radius:6px 6px 0 0">
        <div style="color:#fff;font-size:22px;font-weight:bold;letter-spacing:1px">SGMF Pro</div>
        <div style="color:#F5A800;font-size:11px;letter-spacing:2px;text-transform:uppercase">
          Alertas da frota · {data}</div>
      </div>
      <div style="border:1px solid #D6DEE5;border-top:0;padding:20px 22px;border-radius:0 0 6px 6px">
        <p style="font-size:14px">Resumo automático da manutenção da frota:
          <strong>{len(criticos)}</strong> item(ns) para ação imediata e
          <strong>{len(atencao)}</strong> em atenção.</p>
        {bloco("Ação imediata", criticos)}
        {bloco("Atenção", atencao)}
        <p style="font-size:12px;color:#5F7080;margin-top:26px">
          Mensagem automática do SGMF Pro. Para parar de receber, desligue
          ALERTAS_EMAIL_ATIVO nas configurações do sistema.</p>
      </div>
    </div>"""
    return corpo


def assunto_resumo(alertas):
    criticos = sum(1 for a in alertas if a["nivel"] == "critico")
    data = agora().strftime("%d/%m")
    if criticos:
        return f"[SGMF] {criticos} alerta(s) para ação imediata — {data}"
    return f"[SGMF] Resumo de alertas da frota — {data}"


# ------------------------------------------------------------------ tarefa
def _reservar_execucao():
    """Garante que só um processo envie o aviso do dia."""
    hoje_data = hoje()
    registro = ControleTarefa.query.filter_by(tarefa=TAREFA_DIARIA).first()
    if not registro:
        db.session.add(ControleTarefa(tarefa=TAREFA_DIARIA))
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    resultado = db.session.execute(text("""
        UPDATE controle_tarefas SET ultima_execucao = :hoje
         WHERE tarefa = :tarefa
           AND (ultima_execucao IS NULL OR ultima_execucao < :hoje)"""),
        {"hoje": hoje_data, "tarefa": TAREFA_DIARIA})
    db.session.commit()
    return resultado.rowcount == 1


def _registrar_resultado(texto_resultado):
    registro = ControleTarefa.query.filter_by(tarefa=TAREFA_DIARIA).first()
    if registro:
        registro.ultimo_resultado = texto_resultado[:300]
        registro.atualizado_em = agora()
        db.session.commit()


def executar_alertas_diarios(forcar=False):
    """Monta e envia o resumo do dia. Devolve o que aconteceu."""
    from services import indicadores

    if not current_app.config.get("ALERTAS_EMAIL_ATIVO"):
        return {"enviado": False, "motivo": "Aviso por e-mail desligado (ALERTAS_EMAIL_ATIVO)."}
    if not configurado():
        return {"enviado": False, "motivo": "SMTP não configurado."}
    if not forcar and not _reservar_execucao():
        return {"enviado": False, "motivo": "O aviso de hoje já foi enviado."}

    alertas = indicadores.alertas()
    relevantes = [a for a in alertas if a["nivel"] in ("critico", "atencao")]
    if not relevantes:
        _registrar_resultado("Sem alertas — nada enviado.")
        return {"enviado": False, "motivo": "Nenhum alerta ativo hoje.", "alertas": 0}

    try:
        para = enviar_email(assunto_resumo(relevantes), montar_resumo(relevantes))
    except ErroNegocio as e:
        _registrar_resultado(f"Falhou: {e}")
        return {"enviado": False, "motivo": str(e), "alertas": len(relevantes)}

    _registrar_resultado(f"Enviado para {', '.join(para)} ({len(relevantes)} alertas).")
    return {"enviado": True, "destinatarios": para, "alertas": len(relevantes)}


# --------------------------------------------------------------- agendador
def iniciar_agendador(app):
    """Dispara o resumo uma vez por dia, no horário configurado.

    Roda dentro do próprio sistema, em uma thread de segundo plano. Com mais
    de um processo no ar, todos verificam, mas só um consegue reservar o
    envio do dia — os outros saem sem fazer nada.
    """
    if not app.config.get("ALERTAS_EMAIL_ATIVO"):
        return None

    def laco():
        while True:
            try:
                with app.app_context():
                    if agora().hour == app.config.get("ALERTAS_HORA", 7):
                        resultado = executar_alertas_diarios()
                        if resultado.get("enviado"):
                            print(f"[SGMF] Resumo de alertas enviado: {resultado}")
            except Exception as e:
                print(f"[SGMF] Agendador falhou desta vez: {e.__class__.__name__}: {e}")
            time.sleep(app.config.get("INTERVALO_AGENDADOR", 600))

    thread = threading.Thread(target=laco, name="sgmf-alertas", daemon=True)
    thread.start()
    return thread
