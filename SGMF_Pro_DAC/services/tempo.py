"""Data e hora no fuso da empresa.

O servidor pode operar em UTC. Todo o sistema usa as funções deste módulo
para manter as datas no fuso configurado para a empresa.
"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO_PADRAO = "America/Sao_Paulo"

try:
    FUSO = ZoneInfo(os.environ.get("TZ") or FUSO_PADRAO)
except Exception:
    FUSO = ZoneInfo(FUSO_PADRAO)


def agora():
    """Retorna a data e a hora atuais no fuso da empresa."""
    return datetime.now(FUSO)


def hoje():
    """Retorna a data atual no fuso da empresa."""
    return agora().date()


def formatar(momento, formato="%d/%m/%Y %H:%M"):
    """Converte um momento gravado em UTC para o fuso da empresa."""
    if momento is None:
        return ""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=ZoneInfo("UTC"))
    return momento.astimezone(FUSO).strftime(formato)


def ler_data(valor, campo="data"):
    """Converte datas recebidas pelas telas e informa valores inválidos."""
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    texto = str(valor).strip()
    if "T" in texto:
        texto = texto.split("T", 1)[0]

    try:
        return date.fromisoformat(texto)
    except ValueError:
        from services.crud import ErroNegocio

        raise ErroNegocio(f"O campo {campo} precisa estar no formato AAAA-MM-DD.")
