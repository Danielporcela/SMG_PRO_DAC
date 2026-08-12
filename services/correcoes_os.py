"""Correções incrementais da OS sem apagar ou recriar dados existentes."""
from __future__ import annotations

from extensions import db
from models import ItemOS, Pneu
from services.tempo import hoje


POSICOES_CAMINHAO = (
    "Dianteiro Esquerdo",
    "Dianteiro Direito",
    "Traseiro Esquerdo Externo",
    "Traseiro Esquerdo Interno",
    "Traseiro Direito Externo",
    "Traseiro Direito Interno",
)


def eh_item_pneu(item: ItemOS) -> bool:
    """Reconhece pneu pelo grupo e pela descrição do item ou da peça vinculada."""
    valores = [item.grupo, item.descricao]
    if item.peca is not None:
        valores.extend([item.peca.grupo, item.peca.descricao, item.peca.codigo])
    texto = " ".join(str(v or "") for v in valores).casefold()
    return "pneu" in texto


def posicoes_do_veiculo(veiculo_id: int | None):
    ocupados = {}
    if veiculo_id:
        pneus = (Pneu.query
                 .filter(Pneu.veiculo_id == veiculo_id, Pneu.status == "Em uso")
                 .order_by(Pneu.id.desc()).all())
        for pneu in pneus:
            if pneu.posicao and pneu.posicao not in ocupados:
                ocupados[pneu.posicao] = pneu

    retorno = []
    for nome in POSICOES_CAMINHAO:
        atual = ocupados.get(nome)
        retorno.append({
            "valor": nome,
            "ocupada": atual is not None,
            "pneu_atual_id": atual.id if atual else None,
            "pneu_atual": atual.numero_fogo if atual else None,
            "sulco_mm": atual.sulco_mm if atual else None,
        })
    return retorno


def aplicar_posicao_pneu(item: ItemOS, posicao: str):
    """Registra a posição e baixa o pneu antigo daquela posição.

    Não exclui registros. O pneu retirado permanece no banco como Descartado e
    o ItemOS mantém a referência em pneu_substituido_id.
    """
    if posicao not in POSICOES_CAMINHAO:
        raise ValueError("Posição de pneu inválida.")
    if not eh_item_pneu(item):
        raise ValueError("O item selecionado não foi identificado como pneu.")
    if item.ordem is None or item.ordem.veiculo_id is None:
        raise ValueError("A ordem de serviço precisa estar vinculada a um veículo.")

    # O fluxo de correção trabalha apenas com itens ainda sem posição. Isso
    # evita alterar uma substituição histórica já registrada.
    if item.posicao_pneu and item.posicao_pneu != posicao:
        raise ValueError("Este pneu já possui posição registrada na ordem de serviço.")

    pneu_antigo = (Pneu.query
                   .filter(Pneu.veiculo_id == item.ordem.veiculo_id,
                           Pneu.posicao == posicao,
                           Pneu.status == "Em uso")
                   .order_by(Pneu.id.desc()).first())

    item.posicao_pneu = posicao
    if pneu_antigo is not None:
        item.pneu_substituido_id = pneu_antigo.id
        pneu_antigo.status = "Descartado"
        # Mantemos veículo e posição no histórico do pneu antigo.
        if pneu_antigo.data_medicao is None:
            pneu_antigo.data_medicao = hoje()

    db.session.commit()
    return {
        "item_id": item.id,
        "ordem_servico_id": item.ordem_servico_id,
        "posicao": posicao,
        "pneu_substituido_id": pneu_antigo.id if pneu_antigo else None,
        "pneu_substituido": pneu_antigo.numero_fogo if pneu_antigo else None,
    }
