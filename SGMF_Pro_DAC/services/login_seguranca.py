"""Bloqueio automático de login após tentativas erradas seguidas.

As tabelas TentativaLogin e BloqueioAcesso já existiam em models.py, mas
nunca tinham sido ligadas à rota /login (routes/auth.py). Este módulo faz
essa ligação:

  - registrar_tentativa(): grava cada tentativa (sucesso ou falha) e,
    depois de LIMITE_TENTATIVAS falhas seguidas para o mesmo e-mail OU o
    mesmo IP, cria um BloqueioAcesso.
  - bloqueado(): checa, antes de validar a senha, se o e-mail ou o IP já
    estão bloqueados.

A liberação é sempre manual (feita por um admin) — não expira sozinho,
como já dizia o comentário original em BloqueioAcesso.
"""
from extensions import db
from models import BloqueioAcesso, TentativaLogin

LIMITE_TENTATIVAS = 4


def ip_cliente(request):
    """IP real do cliente. Requer ProxyFix (ver app.py) para não pegar o
    IP interno do proxy do Render em vez do IP de quem está tentando logar.
    """
    return request.access_route[0] if request.access_route else (request.remote_addr or "")


def bloqueado(email, ip):
    """True se o e-mail OU o IP informados estiverem bloqueados e ainda
    não tiverem sido liberados por um administrador."""
    condicoes = []
    if email:
        condicoes.append(db.and_(BloqueioAcesso.tipo == "email", BloqueioAcesso.valor == email))
    if ip:
        condicoes.append(db.and_(BloqueioAcesso.tipo == "ip", BloqueioAcesso.valor == ip))
    if not condicoes:
        return False
    return db.session.query(BloqueioAcesso.id).filter(
        BloqueioAcesso.liberado.is_(False), db.or_(*condicoes)
    ).first() is not None


def _falhas_seguidas(tipo, valor):
    campo = TentativaLogin.email_tentado if tipo == "email" else TentativaLogin.ip
    recentes = (TentativaLogin.query
                .filter(campo == valor)
                .order_by(TentativaLogin.id.desc())
                .limit(LIMITE_TENTATIVAS)
                .all())
    return len(recentes) == LIMITE_TENTATIVAS and all(not t.sucesso for t in recentes)


def registrar_tentativa(email, ip, sucesso):
    """Grava a tentativa de login e cria um bloqueio se o limite foi atingido.

    Uma tentativa com sucesso não bloqueia nada (só zera a sequência, já
    que a checagem olha as últimas N tentativas em ordem).
    """
    db.session.add(TentativaLogin(email_tentado=email or None, ip=ip or None, sucesso=sucesso))
    db.session.flush()

    if not sucesso:
        for tipo, valor in (("email", email), ("ip", ip)):
            if not valor:
                continue
            ja_bloqueado = BloqueioAcesso.query.filter_by(
                tipo=tipo, valor=valor, liberado=False).first()
            if not ja_bloqueado and _falhas_seguidas(tipo, valor):
                db.session.add(BloqueioAcesso(tipo=tipo, valor=valor))

    db.session.commit()
