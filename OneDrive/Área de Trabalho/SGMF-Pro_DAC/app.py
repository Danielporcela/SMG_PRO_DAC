"""SGMF Pro — Sistema de Gestão de Manutenção de Frotas.

Execução local:      python app.py
Execução no Render:  gunicorn app:app
"""
import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from config import Config
from extensions import db, migrate
from services.tempo import hoje


def criar_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)

    for pasta in (app.config["UPLOAD_FOLDER"], app.config["BACKUP_FOLDER"],
                  os.path.join(os.path.dirname(__file__), "database")):
        os.makedirs(pasta, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(__file__), "migrations"))

    from routes.api import bp_api
    from routes.auth import bp_auth, bp_usuarios
    from routes.auth_senha import bp_auth_senha
    from routes.extras import bp_extras
    from routes.paginas import bp_paginas
    from routes.relatorios import bp_relatorios

    app.register_blueprint(bp_auth)
    app.register_blueprint(bp_auth_senha)
    app.register_blueprint(bp_usuarios)
    app.register_blueprint(bp_api)
    app.register_blueprint(bp_extras)
    app.register_blueprint(bp_relatorios)
    app.register_blueprint(bp_paginas)

    @app.context_processor
    def datas_padrao():
        data = hoje()
        return {"hoje": data.isoformat(),
                "primeiro_dia": data.replace(day=1).isoformat(),
                "inicio_periodo": (data - timedelta(days=29)).isoformat(),
                "ano": data.year}

    @app.context_processor
    def permissoes_padrao():
        """Disponibiliza `pode('tela')` para os templates decidirem o que
        mostrar no menu sem repetir a lógica de pesos em cada template.
        """
        pesos = {"nenhum": 0, "visualizar": 1, "editar": 2}

        def pode(tela, nivel_minimo="visualizar"):
            if session.get("perfil") == "admin":
                return True
            nivel_atual = (session.get("permissoes") or {}).get(tela, "nenhum")
            return pesos.get(nivel_atual, 0) >= pesos.get(nivel_minimo, 1)

        return {"pode": pode}

    from services.crud import ErroNegocio

    @app.errorhandler(ErroNegocio)
    def regra_de_negocio(e):
        db.session.rollback()
        if request.path.startswith("/api/"):
            return jsonify({"erro": str(e)}), 400
        return render_template("erro.html", codigo=400, mensagem=str(e)), 400

    @app.errorhandler(404)
    def nao_encontrado(e):
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Endereço não encontrado."}), 404
        if not session.get("usuario_id"):
            return redirect(url_for("auth.login"))
        return render_template("erro.html", codigo=404,
                               mensagem="Esta página não existe no sistema."), 404

    @app.errorhandler(500)
    def erro_interno(e):
        db.session.rollback()
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Erro interno. Tente novamente."}), 500
        return render_template("erro.html", codigo=500,
                               mensagem="Algo falhou ao processar. Tente novamente."), 500

    @app.get("/saude")
    def saude():
        """Usado pelo Render para verificar se a aplicação está no ar."""
        return {"status": "ok", "data": hoje().isoformat()}

    with app.app_context():
        preparar_banco()
        try:
            criar_admin_inicial()
        except Exception as e:
            # Acontece quando o banco ainda não recebeu a migração mais recente
            # (ex.: durante "flask db migrate"/"flask db upgrade", que importam
            # este arquivo antes de aplicar a mudança de estrutura). Não é
            # motivo para travar: a checagem roda de novo no próximo start,
            # já com o banco atualizado.
            db.session.rollback()
            print(f"[SGMF] Verificação do usuário inicial adiada: {e}")

        try:
            from services.alertas import sincronizar_estados
            sincronizar_estados()
        except Exception as e:
            db.session.rollback()
            print(f"[SGMF] Sincronização inicial de alertas adiada: {e}")

    if app.config.get("AGENDADOR_ATIVO") and not app.config.get("TESTING"):
        from services.notificacoes import iniciar_agendador
        iniciar_agendador(app)

    return app


def preparar_banco():
    """Banco novo: cria as tabelas e marca a versão atual.

    Banco que já existe: nada é tocado aqui — mudanças de estrutura passam
    por `flask db migrate` e `flask db upgrade`, para não perder dados.
    """
    from sqlalchemy import inspect

    from flask_migrate import stamp

    inspetor = inspect(db.engine)
    if inspetor.has_table("alembic_version"):
        return
    db.create_all()

    pasta = os.path.join(os.path.dirname(__file__), "migrations")
    if not os.path.isdir(os.path.join(pasta, "versions")):
        return
    try:
        stamp()
    except (Exception, SystemExit) as e:
        print(f"[SGMF] Estrutura criada sem marcar a versão: {e}")


def criar_admin_inicial():
    """Cria o primeiro acesso se o banco estiver vazio."""
    from models import Usuario
    if Usuario.query.count():
        return
    admin = Usuario(nome=os.environ.get("ADMIN_NOME", "Administrador"),
                    email=os.environ.get("ADMIN_EMAIL", "admin@sgmf.local").lower(),
                    perfil="admin")
    admin.definir_senha(os.environ.get("ADMIN_SENHA", "admin123"))
    db.session.add(admin)
    db.session.commit()
    print(f"[SGMF] Usuário inicial criado: {admin.email}")


app = criar_app()


if __name__ == "__main__":
    with app.app_context():
        try:
            from flask_migrate import upgrade
            upgrade()
        except (Exception, SystemExit) as e:
            db.session.rollback()
            print(f"[SGMF] Falha ao atualizar a estrutura do banco: {e}")

    porta = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=porta, debug=os.environ.get("FLASK_ENV") != "production")
