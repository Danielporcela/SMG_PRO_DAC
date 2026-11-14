"""Ciclo de vida do pneu: retirado da frota -> recapagem -> estoque ou descarte.

Fluxo:
  1. Pneu sai da frota (troca na OS)           -> status "Retirado"
  2. Pneu enviado à recapadora (opcional)      -> status "Em recapagem"
  3. Volta da recapagem com NOTA FISCAL, listando os números de fogo:
       - Recapado   -> status "Estoque" e `vida` = "1ª recapagem", "2ª recapagem"...
       - Descartado -> status "Descartado" (lista de descarte)
  4. Também é possível descartar direto da lista de retirados.

Nada altera a tabela `pneus`: o nº da recapagem fica em `vida` (campo que já
existia) e cada passo fica gravado em `pneus_ciclo`. As tabelas novas são
criadas de forma compatível com bancos existentes.
"""
from __future__ import annotations

import re
from datetime import datetime

from extensions import db

STATUS_RETIRADO = "Retirado"
STATUS_EM_RECAPAGEM = "Em recapagem"
STATUS_ESTOQUE = "Estoque"
STATUS_DESCARTADO = "Descartado"

STATUS_PNEU_VALIDOS = ("Em uso", "Estoque", "Descartado", STATUS_RETIRADO, STATUS_EM_RECAPAGEM)


class NotaRecapagem(db.Model):
    """Nota fiscal de retorno da recapagem (com os números de fogo)."""
    __tablename__ = "notas_recapagem_pneu"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(30), nullable=False, index=True)
    serie = db.Column(db.String(10))
    data_emissao = db.Column(db.Date)
    data_entrada = db.Column(db.Date)
    fornecedor_id = db.Column(db.Integer, index=True)
    fornecedor_nome = db.Column(db.String(160))
    observacao = db.Column(db.String(300))
    usuario = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self, itens=None):
        d = {
            "id": self.id, "numero": self.numero, "serie": self.serie,
            "identificacao": f"NF {self.numero}" + (f"/{self.serie}" if self.serie else ""),
            "data_emissao": self.data_emissao.isoformat() if self.data_emissao else None,
            "data_entrada": self.data_entrada.isoformat() if self.data_entrada else None,
            "fornecedor_id": self.fornecedor_id, "fornecedor_nome": self.fornecedor_nome,
            "observacao": self.observacao, "usuario": self.usuario,
        }
        if itens is not None:
            d["itens"] = [i.to_dict() for i in itens]
            d["valor_total"] = round(sum(i.valor or 0 for i in itens), 2)
            d["qtd_itens"] = len(itens)
        return d


class PneuCiclo(db.Model):
    """Uma linha para cada passo da vida do pneu (retirada, envio, retorno, descarte)."""
    __tablename__ = "pneus_ciclo"

    id = db.Column(db.Integer, primary_key=True)
    pneu_id = db.Column(db.Integer, nullable=False, index=True)
    numero_fogo = db.Column(db.String(30), index=True)
    evento = db.Column(db.String(30), nullable=False)  # Retirada | Envio recapagem | Retorno recapagem | Descarte
    data = db.Column(db.Date)
    veiculo_id = db.Column(db.Integer)
    veiculo_rotulo = db.Column(db.String(80))
    posicao = db.Column(db.String(60))
    ordem_servico_numero = db.Column(db.String(20))
    vida = db.Column(db.String(20))          # vida do pneu após o evento
    nota_id = db.Column(db.Integer, index=True)
    nota_numero = db.Column(db.String(40))
    fornecedor_nome = db.Column(db.String(160))
    valor = db.Column(db.Float)
    motivo = db.Column(db.String(300))
    usuario = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id, "pneu_id": self.pneu_id, "numero_fogo": self.numero_fogo,
            "evento": self.evento,
            "data": self.data.isoformat() if self.data else None,
            "veiculo_id": self.veiculo_id, "veiculo_rotulo": self.veiculo_rotulo,
            "posicao": self.posicao, "ordem_servico_numero": self.ordem_servico_numero,
            "vida": self.vida, "nota_id": self.nota_id, "nota_numero": self.nota_numero,
            "fornecedor_nome": self.fornecedor_nome, "valor": self.valor,
            "motivo": self.motivo, "usuario": self.usuario,
            "criado_em": self.criado_em.isoformat() if self.criado_em else None,
        }


def garantir_tabelas_recapagem_pneus():
    """Cria as tabelas novas sem exigir migração no banco já existente."""
    NotaRecapagem.__table__.create(bind=db.engine, checkfirst=True)
    PneuCiclo.__table__.create(bind=db.engine, checkfirst=True)


# ------------------------------------------------------------------ vida
def numero_recapagem(vida):
    """'Novo' -> 0 · '1ª recapagem' -> 1 · '2ª recapagem' -> 2."""
    achou = re.search(r"(\d+)", str(vida or ""))
    return int(achou.group(1)) if achou else 0


def rotulo_vida(n):
    return "Novo" if n <= 0 else f"{n}ª recapagem"


def proxima_vida(vida_atual):
    return rotulo_vida(numero_recapagem(vida_atual) + 1)


# ---------------------------------------------------------------- eventos
def registrar_ciclo(pneu, evento, data=None, usuario=None, **extra):
    """Grava um passo do ciclo. Não faz commit."""
    reg = PneuCiclo(
        pneu_id=pneu.id, numero_fogo=pneu.numero_fogo, evento=evento, data=data,
        vida=pneu.vida, usuario=usuario, **extra)
    db.session.add(reg)
    return reg


def ultimo_evento(pneu_id, evento):
    return (PneuCiclo.query.filter_by(pneu_id=pneu_id, evento=evento)
            .order_by(PneuCiclo.id.desc()).first())
