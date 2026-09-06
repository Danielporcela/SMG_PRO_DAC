import secrets

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

from extensions import db
from models import CARGOS_SUGERIDOS, TELAS_SISTEMA, BloqueioAcesso, Usuario
from services.crud import login_obrigatorio, perfil_obrigatorio, registrar_crud
from services.login_seguranca import bloqueado, ip_cliente, registrar_tentativa
from services.tempo import agora

bp_auth = Blueprint("auth", __name__)


@bp_auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("usuario_id"):
            return redirect(url_for("paginas.dashboard"))
        return render_template("login.html")

    dados = request.get_json(silent=True) or request.form
    email = (dados.get("email") or "").strip().lower()
    ip = ip_cliente(request)

    if bloqueado(email, ip):
        return jsonify({"erro": "Acesso bloqueado após várias tentativas erradas. "
                                "Fale com um administrador para liberar."}), 403

    usuario = Usuario.query.filter_by(email=email).first()
    autenticado = bool(usuario and usuario.conferir_senha(dados.get("senha") or ""))
    registrar_tentativa(email, ip, autenticado)

    if not autenticado:
        return jsonify({"erro": "E-mail ou senha não conferem."}), 401
    if not usuario.ativo:
        return jsonify({"erro": "Este acesso está desativado. Fale com o administrador."}), 403

    session.permanent = True
    session["usuario_id"] = usuario.id
    session["usuario_nome"] = usuario.nome
    session["perfil"] = usuario.perfil
    session["cargo"] = usuario.cargo or ""
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
                    "perfil": session.get("perfil"), "cargo": session.get("cargo")})


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
        # Antes usava a senha fixa "sgmf@123" para todo usuário novo sem
        # senha informada — documentada até na tela de Usuários. Gera uma
        # senha aleatória por usuário e devolve na resposta desta chamada
        # (ver _serializar_usuario), para o admin repassar uma única vez.
        senha_gerada = secrets.token_urlsafe(9)
        obj.definir_senha(senha_gerada)
        obj._senha_gerada = senha_gerada


def _depois_salvar_usuario(obj, dados, anterior):
    """Grava a matriz de telas enviada junto do cadastro, se houver.

    `dados["permissoes"]` é uma lista [{"tela": "...", "nivel": "..."}]
    montada pela grade de telas da tela de Usuários. Quando ausente (ex.:
    criação via API sem esse campo), as permissões do usuário continuam
    valendo pelo padrão do perfil (ver Usuario.permissoes_mapa).
    """
    if "permissoes" in dados:
        obj.definir_permissoes(dados.get("permissoes") or [])


def _serializar_usuario(obj):
    dados = obj.to_dict()
    senha_gerada = getattr(obj, "_senha_gerada", None)
    if senha_gerada:
        # Só existe no objeto em memória logo após a criação (não é coluna
        # do banco); aparece uma única vez, nesta resposta.
        dados["senha_gerada"] = senha_gerada
    return dados


registrar_crud(bp_usuarios, "usuarios", Usuario,
               campos={"nome": "str", "email": "str", "perfil": "str",
                       "cargo": "str", "ativo": "bool"},
               ordem=Usuario.nome, obrigatorios=("nome", "email"),
               antes_salvar=_antes_salvar_usuario, depois_salvar=_depois_salvar_usuario,
               serializar=_serializar_usuario)


@bp_usuarios.before_request
@perfil_obrigatorio("admin")
def _somente_admin():
    return None


@bp_usuarios.get("/bloqueios")
def listar_bloqueios():
    """Bloqueios de login ativos (e-mail ou IP), para a tela de Auditoria."""
    ativos = (BloqueioAcesso.query.filter_by(liberado=False)
              .order_by(BloqueioAcesso.criado_em.desc()).all())
    return jsonify([b.to_dict() for b in ativos])


@bp_usuarios.post("/bloqueios/<int:bloqueio_id>/liberar")
def liberar_bloqueio(bloqueio_id):
    bloqueio = db.get_or_404(BloqueioAcesso, bloqueio_id)
    bloqueio.liberado = True
    bloqueio.liberado_por = session.get("usuario_nome")
    bloqueio.liberado_em = agora()
    db.session.commit()
    return jsonify({"ok": True})


@bp_usuarios.get("/telas")
def listar_telas():
    """Alimenta a grade de permissões da tela de Usuários: as telas
    disponíveis, agrupadas, e os cargos sugeridos para preenchimento rápido.
    """
    telas = [{"chave": chave, "rotulo": rotulo, "grupo": grupo}
             for chave, rotulo, grupo in TELAS_SISTEMA]
    return jsonify({"telas": telas, "cargos_sugeridos": CARGOS_SUGERIDOS})
