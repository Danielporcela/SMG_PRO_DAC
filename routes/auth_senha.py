"""Recuperação de senha — 'Esqueceu a senha?'.

Fluxo:
  1. GET  /esqueci-senha            -> formulário pedindo o e-mail
  2. POST /esqueci-senha            -> gera token e envia e-mail com o link
  3. GET  /redefinir-senha/<token>  -> formulário de nova senha
  4. POST /redefinir-senha/<token>  -> grava a nova senha e limpa o token
"""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from extensions import db
from models import Usuario
from services.crud import ErroNegocio
from services.notificacoes import enviar_email
from services.tempo import agora

bp_auth_senha = Blueprint("auth_senha", __name__)


def _montar_email_reset(usuario, link):
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:auto;color:#16202B">
      <div style="background:#0E141B;padding:18px 22px;border-radius:6px 6px 0 0">
        <div style="color:#fff;font-size:22px;font-weight:bold;letter-spacing:1px">SGMF Pro</div>
        <div style="color:#F5A800;font-size:11px;letter-spacing:2px;text-transform:uppercase">
          Redefinição de senha</div>
      </div>
      <div style="border:1px solid #D6DEE5;border-top:0;padding:20px 22px;border-radius:0 0 6px 6px">
        <p style="font-size:14px">Olá, {usuario.nome}.</p>
        <p style="font-size:14px">Recebemos um pedido para redefinir sua senha no SGMF Pro.
          Clique no botão abaixo para escolher uma nova senha (link válido por 1 hora):</p>
        <p style="text-align:center;margin:28px 0">
          <a href="{link}" style="background:#F5A800;color:#0E141B;font-weight:bold;
             text-decoration:none;padding:12px 28px;border-radius:6px;font-size:14px;
             display:inline-block">Criar nova senha</a>
        </p>
        <p style="font-size:12px;color:#5F7080">Se o botão não funcionar, copie e cole este
          endereço no navegador:<br>{link}</p>
        <p style="font-size:12px;color:#5F7080;margin-top:22px">
          Se você não pediu essa alteração, ignore este e-mail — sua senha continua a mesma.</p>
      </div>
    </div>"""


@bp_auth_senha.get("/esqueci-senha")
def esqueci_senha():
    return render_template("esqueci_senha.html")


@bp_auth_senha.post("/esqueci-senha")
def esqueci_senha_enviar():
    email = (request.form.get("email") or "").strip().lower()
    usuario = Usuario.query.filter_by(email=email, ativo=True).first()

    # Mesma mensagem tanto se o e-mail existir quanto se não existir,
    # para não revelar quais e-mails estão cadastrados no sistema.
    mensagem_padrao = ("Se este e-mail estiver cadastrado, você vai receber "
                        "um link para redefinir a senha em instantes.")

    if usuario:
        token = usuario.gerar_token_reset()
        db.session.commit()

        link = url_for("auth_senha.redefinir_senha", token=token, _external=True)
        try:
            enviar_email(assunto="SGMF Pro — Redefinição de senha",
                         corpo_html=_montar_email_reset(usuario, link),
                         destinatarios=[usuario.email])
        except ErroNegocio as e:
            # Não expõe o motivo ao usuário (evita confirmar/negar cadastro
            # e evita vazar detalhes de configuração de SMTP); fica no log do servidor.
            print(f"[SGMF] Falha ao enviar e-mail de redefinição para {usuario.email}: {e}")

    flash(mensagem_padrao, "info")
    return redirect(url_for("auth_senha.esqueci_senha"))


@bp_auth_senha.get("/redefinir-senha/<token>")
def redefinir_senha(token):
    usuario = Usuario.query.filter_by(token_reset=token).first()
    if not usuario or not usuario.token_reset_valido(token):
        flash("Este link expirou ou já foi usado. Peça um novo.", "erro")
        return redirect(url_for("auth_senha.esqueci_senha"))
    return render_template("redefinir_senha.html", token=token)


@bp_auth_senha.post("/redefinir-senha/<token>")
def redefinir_senha_salvar(token):
    usuario = Usuario.query.filter_by(token_reset=token).first()
    if not usuario or not usuario.token_reset_valido(token):
        flash("Este link expirou ou já foi usado. Peça um novo.", "erro")
        return redirect(url_for("auth_senha.esqueci_senha"))

    senha = request.form.get("senha") or ""
    confirmar = request.form.get("confirmar_senha") or ""

    if len(senha) < 6:
        flash("A senha precisa ter pelo menos 6 caracteres.", "erro")
        return render_template("redefinir_senha.html", token=token)

    if senha != confirmar:
        flash("As senhas não coincidem.", "erro")
        return render_template("redefinir_senha.html", token=token)

    usuario.definir_senha(senha)
    usuario.limpar_token_reset()
    db.session.commit()

    flash("Senha redefinida com sucesso. Faça login com a nova senha.", "sucesso")
    return redirect(url_for("auth.login"))
