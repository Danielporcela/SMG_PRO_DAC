"""Horário local centralizado do SGMF Pro."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo


def _fuso():
    nome = os.environ.get("TZ", "America/Sao_Paulo")
    try:
        return ZoneInfo(nome)
    except Exception:
        return ZoneInfo("America/Sao_Paulo")


def agora():
    return datetime.now(_fuso())


def hoje():
    return agora().date()
