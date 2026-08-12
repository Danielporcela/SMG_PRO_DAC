"""Data e hora no fuso da empresa.

O servidor do Render roda em UTC. Sem isso, um abastecimento lançado às 21h
em Brasília seria gravado com a data do dia seguinte. Todo o sistema usa
`hoje()` e `agora()` daqui — nunca `date.today()` direto.

O fuso vem da variável de ambiente TZ (padrão: America/Sao_Paulo).
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

FUSO_PADRAO = "America/Sao_Paulo"

try:
    FUSO = ZoneInfo(os.environ.get("TZ") or FUSO_PADRAO)
except Exception:  # fuso inválido na variável de ambiente
    FUSO = ZoneInfo(FUSO_PADRAO)


def agora():
    """Data e hora atuais no fuso da empresa."""
    return datetime.now(FUSO)


def hoje():
    """Data de hoje no fuso da empresa."""
    return agora().date()


def formatar(momento, formato="%d/%m/%Y %H:%M"):
    """Converte um momento gravado em UTC para o fuso da empresa."""
    if momento is None:
        return ""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZoneInfo("UTC"))
    return momento.astimezone(FUSO).strftime(formato)


def ler_data(texto, campo="data"):
    """Lê uma data vinda da tela. Texto inválido vira erro tratado, não falha."""
    from datetime import date as _date
    if texto in (None, ""):
        return None
    if isinstance(texto, _date):
        return texto
    limpo = str(texto).strip()
    if "T" in limpo:            # aceita data com hora (2026-08-01T10:30)
        limpo = limpo.split("T")[0]
    try:
        return _date.fromisoformat(limpo)
    except ValueError:
        from services.crud import ErroNegocio
        raise ErroNegocio(f"O campo {campo} precisa estar no formato AAAA-MM-DD.")
