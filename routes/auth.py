from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

from extensions import db
from models import CARGOS_SUGERIDOS, TELAS_SISTEMA, BloqueioAcesso, TentativaLogin, Usuario
from services.crud import login_obrigatorio, perfil_obrigatorio, registrar_crud, registrar_log
from services.tempo import agora

bp_auth = Blueprint("auth", __name__)

LIMITE_TENTATIVAS = 4  # a 5ª tentativa errada gera o bloqueio


def _ip_do_pedido():
    """Pega o IP real mesmo atrás do proxy do Render (cabeçalho X-Forwarded-For)."""
    encaminhado = request.headers.get("X-Forwarded-For", "")
    if encaminhado:
        return encaminhado.split(",")[0].strip()
    return request.remote_addr or "desconhecido"


def _bloqueio_ativo(tipo, valor):
    if not valor:
        return None
    return (BloqueioAcesso.query
            .filter_by(tipo=tipo, valor=valor, liberado=False)
            .order_by(BloqueioAcesso.id.desc()).first())


def _tentativas_seguidas_sem_sucesso(tipo, valor):
    """Conta as falhas mais recentes até achar um sucesso ou acabar o histórico —
    é essa sequência sem interrupção que decide o bloqueio."""
    if not valor:
        return 0
    campo = TentativaLogin.ip if tipo == "ip" else TentativaLogin.email_tentado
    recentes = (TentativaLogin.query
                .filter(campo == valor)
                .order_by(TentativaLogin.id.desc())
                .limit(50).all())
    contagem = 0
    for t in recentes:
        if t.sucesso:
            break
        contagem += 1
    return contagem


def _criar_bloqueio_e_avisar(tipo, valor, ip, email_tentado):
    from services.notificacoes import enviar_email  # import tardio evita ciclo de import

    if _bloqueio_ativo(tipo, valor):
        return
    db.session.add(BloqueioAcesso(tipo=tipo, valor=valor))
    registrar_log("bloquear", "acesso", 0, f"{tipo}: {valor}")

    try:
        assunto = f"SGMF Pro | Acesso bloqueado ({tipo}: {valor})"
        corpo = (
            "SGMF Pro\n\n"
            f"Bloqueio automático após {LIMITE_TENTATIVAS + 1} tentativas de login erradas seguidas.\n"
            f"Tipo do bloqueio: {tipo}\n"
            f"Valor bloqueado: {valor}\n"
            f"IP da última tentativa: {ip}\n"
            f"E-mail tentado: {email_tentado or '—'}\n\n"
            "A liberação é manual, na tela Auditoria > Tentativas de login."
        )
        enviar_email(assunto, corpo)
    except Exception:
        pass  # o bloqueio vale mesmo se o e-mail de aviso falhar


@bp_auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("usuario_id"):
            return redirect(url_for("paginas.dashboard"))
        return render_template("login.html")

    dados = request.get_json(silent=True) or request.form
    email = (dados.get("email") or "").strip().lower()
    ip = _ip_do_pedido()

    # Bloqueio já ativo (por IP ou por e-mail) — nem chega a conferir a senha.
    bloqueio = _bloqueio_ativo("ip", ip) or _bloqueio_ativo("email", email)
    if bloqueio:
        return jsonify({
            "bloqueado": True, "ip": ip,
            "mensagem": "Você errou as tentativas de login da página.",
        }), 403

    usuario = Usuario.query.filter_by(email=email).first()
    sucesso = bool(usuario and usuario.ativo and usuario.conferir_senha(dados.get("senha") or ""))

    db.session.add(TentativaLogin(email_tentado=email, ip=ip, sucesso=sucesso))

    if not sucesso:
        db.session.flush()
        falhas_ip = _tentativas_seguidas_sem_sucesso("ip", ip)
        falhas_email = _tentativas_seguidas_sem_sucesso("email", email)
        if falhas_ip > LIMITE_TENTATIVAS:
            _criar_bloqueio_e_avisar("ip", ip, ip, email)
        if email and falhas_email > LIMITE_TENTATIVAS:
            _criar_bloqueio_e_avisar("email", email, ip, email)
        db.session.commit()

        if falhas_ip > LIMITE_TENTATIVAS or falhas_email > LIMITE_TENTATIVAS:
            return jsonify({
                "bloqueado": True, "ip": ip,
                "mensagem": "Você errou as tentativas de login da página.",
            }), 403

        if not usuario:
            return jsonify({"erro": "E-mail ou senha não conferem."}), 401
        if not usuario.ativo:
            return jsonify({"erro": "Este acesso está desativado. Fale com o administrador."}), 403
        return jsonify({"erro": "E-mail ou senha não conferem."}), 401

    db.session.commit()

    session.permanent = True
    session["usuario_id"] = usuario.id
    session["usuario_nome"] = usuario.nome
    session["perfil"] = usuario.perfil
    # Mapa {tela: nivel} calculado uma vez no login — evita ir ao banco a
    # cada clique só para saber se a tela está liberada.
    session["permissoes"] = usuario.permissoes_mapa()
    return jsonify({"ok": True, "usuario": usuario.to_dict()})


@bp_auth.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp_auth.get("/api/eu")
@login_obrigatorio
def eu():
    return jsonify({"id": session["usuario_id"], "nome": session["usuario_nome"],
                    "perfil": session.get("perfil")})


@bp_auth.post("/api/trocar-senha")
@login_obrigatorio
def trocar_senha():
    dados = request.get_json(silent=True) or {}
    usuario = db.session.get(Usuario, session["usuario_id"])
    if not usuario.conferir_senha(dados.get("atual") or ""):
        return jsonify({"erro": "A senha atual não confere."}), 400
    nova = dados.get("nova") or ""
    if len(nova) < 6:
        return jsonify({"erro": "A nova senha precisa de pelo menos 6 caracteres."}), 400
    usuario.definir_senha(nova)
    db.session.commit()
    return jsonify({"ok": True})


# --- gestão de usuários (somente admin) -------------------------------------
bp_usuarios = Blueprint("usuarios", __name__, url_prefix="/api")


def _antes_salvar_usuario(obj, dados, anterior):
    if dados.get("email"):
        obj.email = dados["email"].strip().lower()
    if dados.get("senha"):
        obj.definir_senha(dados["senha"])
    elif not obj.senha_hash:
        obj.definir_senha("sgmf@123")


def _depois_salvar_usuario(obj, dados, anterior):
    """Grava a matriz de telas enviada junto do cadastro, se houver.

    `dados["permissoes"]` é uma lista [{"tela": "...", "nivel": "..."}]
    montada pela grade de telas da tela de Usuários. Quando ausente (ex.:
    criação via API sem esse campo), as permissões do usuário continuam
    valendo pelo padrão do perfil (ver Usuario.permissoes_mapa).
    """
    if "permissoes" in dados:
        obj.definir_permissoes(dados.get("permissoes") or [])


registrar_crud(bp_usuarios, "usuarios", Usuario,
               campos={"nome": "str", "email": "str", "perfil": "str",
                       "cargo": "str", "ativo": "bool"},
               ordem=Usuario.nome, obrigatorios=("nome", "email"),
               antes_salvar=_antes_salvar_usuario, depois_salvar=_depois_salvar_usuario)


@bp_usuarios.before_request
@perfil_obrigatorio("admin")
def _somente_admin():
    return None


@bp_usuarios.get("/telas")
def listar_telas():
    """Alimenta a grade de permissões da tela de Usuários: as telas
    disponíveis, agrupadas, e os cargos sugeridos para preenchimento rápido.
    """
    telas = [{"chave": chave, "rotulo": rotulo, "grupo": grupo}
             for chave, rotulo, grupo in TELAS_SISTEMA]
    return jsonify({"telas": telas, "cargos_sugeridos": CARGOS_SUGERIDOS})


# --------------------------------------------- tentativas e bloqueios de login
@bp_usuarios.get("/tentativas_login")
def listar_tentativas_login():
    """500 tentativas mais recentes — o "relatório de quem tentou acessar"."""
    tentativas = (TentativaLogin.query
                  .order_by(TentativaLogin.id.desc()).limit(500).all())
    return jsonify([t.to_dict() for t in tentativas])


@bp_usuarios.get("/bloqueios_acesso")
def listar_bloqueios_acesso():
    bloqueios = BloqueioAcesso.query.order_by(BloqueioAcesso.id.desc()).limit(200).all()
    return jsonify([b.to_dict() for b in bloqueios])


@bp_usuarios.post("/bloqueios_acesso/<int:bloqueio_id>/liberar")
def liberar_bloqueio_acesso(bloqueio_id):
    from flask import session as _session

    bloqueio = db.session.get(BloqueioAcesso, bloqueio_id)
    if not bloqueio:
        return jsonify({"erro": "Bloqueio não encontrado."}), 404
    bloqueio.liberado = True
    bloqueio.liberado_por = _session.get("usuario_nome")
    bloqueio.liberado_em = agora()
    registrar_log("liberar", "acesso", bloqueio.id, f"{bloqueio.tipo}: {bloqueio.valor}")
    db.session.commit()
    return jsonify(bloqueio.to_dict())
