"""Mapa interativo de pneus do SGMF.

Mantém os dados adicionais do mapa (DOT e observações) e o histórico de
instalações, trocas e rodízios sem alterar a tabela principal `pneus`.
As tabelas são criadas de forma compatível com bancos existentes.
"""
from __future__ import annotations

from datetime import datetime

from extensions import db


class PneuMapaDados(db.Model):
    __tablename__ = "pneus_mapa_dados"

    id = db.Column(db.Integer, primary_key=True)
    pneu_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    dot = db.Column(db.String(20))
    observacao = db.Column(db.String(500))
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "pneu_id": self.pneu_id,
            "dot": self.dot,
            "observacao": self.observacao,
            "atualizado_em": self.atualizado_em.isoformat() if self.atualizado_em else None,
        }


class PneuHistorico(db.Model):
    __tablename__ = "pneus_historico"

    id = db.Column(db.Integer, primary_key=True)
    pneu_id = db.Column(db.Integer, index=True)
    numero_fogo = db.Column(db.String(30))
    veiculo_id = db.Column(db.Integer, index=True)
    posicao = db.Column(db.String(60))
    dot = db.Column(db.String(20))
    sulco_mm = db.Column(db.Float)
    km = db.Column(db.Float)
    status = db.Column(db.String(20))
    evento = db.Column(db.String(30), nullable=False)
    detalhe = db.Column(db.String(500))
    usuario = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "pneu_id": self.pneu_id,
            "numero_fogo": self.numero_fogo,
            "veiculo_id": self.veiculo_id,
            "posicao": self.posicao,
            "dot": self.dot,
            "sulco_mm": self.sulco_mm,
            "km": self.km,
            "status": self.status,
            "evento": self.evento,
            "detalhe": self.detalhe,
            "usuario": self.usuario,
            "criado_em": self.criado_em.isoformat() if self.criado_em else None,
        }


def garantir_tabelas_mapa_pneus():
    """Cria as tabelas novas sem exigir uma migração no banco já existente."""
    PneuMapaDados.__table__.create(bind=db.engine, checkfirst=True)
    PneuHistorico.__table__.create(bind=db.engine, checkfirst=True)
