import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Configuração base. Em produção (Render) tudo vem de variáveis de ambiente."""

    SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")

    # Render entrega a URL do Postgres em DATABASE_URL (prefixo postgres://)
    _db_url = os.environ.get("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url or "sqlite:///" + os.path.join(BASE_DIR, "database", "sgmf.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("FLASK_ENV") == "production"

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    BACKUP_FOLDER = os.path.join(BASE_DIR, "backup")
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

    # ------------------------------------------------------------- anexos
    TAMANHO_MAXIMO_ANEXO = int(os.environ.get("TAMANHO_MAXIMO_ANEXO", 5 * 1024 * 1024))
    TIPOS_ANEXO = ["image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"]

    # -------------------------------------------------- aviso por e-mail
    # Vem desligado: sem SMTP_SENHA o sistema não tenta enviar nada.
    # No Gmail, gere uma "senha de aplicativo" (Conta Google > Segurança >
    # Verificação em duas etapas > Senhas de app) e coloque em SMTP_SENHA.
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORTA = int(os.environ.get("SMTP_PORTA", 587))
    SMTP_USUARIO = os.environ.get("SMTP_USUARIO", "estudosti20@gmail.com")
    SMTP_SENHA = os.environ.get("SMTP_SENHA", "")
    SMTP_TLS = os.environ.get("SMTP_TLS", "1") == "1"
    SMTP_SSL = os.environ.get("SMTP_SSL", "0") == "1"
    EMAIL_REMETENTE = os.environ.get("EMAIL_REMETENTE", "estudosti20@gmail.com")
    EMAIL_DESTINATARIOS = os.environ.get("EMAIL_DESTINATARIOS", "estudosti20@gmail.com")

    ALERTAS_EMAIL_ATIVO = os.environ.get("ALERTAS_EMAIL_ATIVO", "1") == "1"
    ALERTAS_HORA = int(os.environ.get("ALERTAS_HORA", 7))          # hora local do envio
    INTERVALO_AGENDADOR = int(os.environ.get("INTERVALO_AGENDADOR", 600))
    AGENDADOR_ATIVO = os.environ.get("AGENDADOR_ATIVO", "1") == "1"
    CHAVE_TAREFAS = os.environ.get("CHAVE_TAREFAS", "")            # protege a URL do disparo

    # Regras de negócio (podem ser ajustadas sem mexer no código)
    SULCO_MINIMO_MM = float(os.environ.get("SULCO_MINIMO_MM", 4.0))
    KM_AVISO_TROCA_OLEO = int(os.environ.get("KM_AVISO_TROCA_OLEO", 500))
    DESVIO_CONSUMO_ALERTA = float(os.environ.get("DESVIO_CONSUMO_ALERTA", 0.15))  # 15% pior que a média
