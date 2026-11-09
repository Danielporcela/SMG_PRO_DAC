"""Registro e consulta dos logins (aba "Relatório de acesso")."""
from collections import OrderedDict

from extensions import db
from models import AcessoLogin
from services.tempo import agora


def garantir_tabela_acessos_login():
    """Cria a tabela `acessos_login` se ainda não existir (idempotente)."""
    AcessoLogin.__table__.create(bind=db.engine, checkfirst=True)


def registrar_acesso(usuario, ip=""):
    """Grava um login bem-sucedido. Nunca derruba o login se falhar."""
    try:
        momento = agora().replace(tzinfo=None)
        db.session.add(AcessoLogin(
            usuario_id=usuario.id, usuario_nome=usuario.nome,
            email=usuario.email, ip=(ip or "")[:64],
            data=momento.date(), momento=momento))
        db.session.commit()
    except Exception:
        db.session.rollback()


def acessos_do_dia(dia):
    """Resumo por usuário + lista completa de acessos de uma data."""
    linhas = (AcessoLogin.query.filter(AcessoLogin.data == dia)
              .order_by(AcessoLogin.momento.asc()).all())

    resumo = OrderedDict()
    detalhes = []
    for a in linhas:
        chave = a.usuario_id or a.email
        r = resumo.setdefault(chave, {
            "usuario": a.usuario_nome or a.email or "—", "email": a.email or "",
            "quantidade": 0, "primeiro": None, "ultimo": None})
        hora = a.momento.strftime("%H:%M:%S")
        r["quantidade"] += 1
        r["primeiro"] = r["primeiro"] or hora
        r["ultimo"] = hora
        detalhes.append({"usuario": r["usuario"], "email": r["email"],
                         "data": a.data.strftime("%d/%m/%Y"),
                         "horario": hora, "ip": a.ip or ""})

    resumo = sorted(resumo.values(), key=lambda r: (-r["quantidade"], r["usuario"].lower()))
    return {"data": dia.isoformat(), "total_acessos": len(detalhes),
            "total_usuarios": len(resumo), "resumo": resumo,
            "acessos": list(reversed(detalhes))}
