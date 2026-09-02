from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

from extensions import db
from models import CARGOS_SUGERIDOS, TELAS_SISTEMA, Usuario
from services.crud import login_obrigatorio, perfil_obrigatorio, registrar_crud

bp_auth = Blueprint("auth", __name__)


@bp_auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("usuario_id"):
            return redirect(url_for("paginas.dashboard"))
        return render_template("login.html")

    dados = request.get_json(silent=True) or request.form
    usuario = Usuario.query.filter_by(email=(dados.get("email") or "").strip().lower()).first()
    if not usuario or not usuario.conferir_senha(dados.get("senha") or ""):
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
