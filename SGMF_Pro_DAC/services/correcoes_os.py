"""Correções incrementais da OS sem apagar ou recriar dados existentes.

Atualização:
  * as posições passaram a ser agrupadas por eixo e ganharam o EIXO TRUCK
    (2º eixo traseiro), além do dianteiro e do de tração;
  * o lançamento do pneu na OS aceita o número de fogo, gerando a
    identificação completa no item
    (ex.: "Pneu truck traseiro interno esquerdo — nº 3456");
  * o pneu informado passa a ser criado/atualizado no módulo de Pneus,
    já em uso, no veículo e na posição escolhida.

Não exige migração: as colunas usadas já existem.
"""
from __future__ import annotations

import unicodedata

from extensions import db
from models import ItemOS, Pneu, Veiculo
from services.tempo import hoje

EIXO_DIANTEIRO = "Eixo dianteiro"
EIXO_TRACAO = "Eixo de tração"
EIXO_TRUCK = "Eixo truck"
EIXO_ESTEPE = "Estepe"

# Valor gravado no banco (a coluna aceita 40 caracteres) e o eixo a que pertence.
POSICOES = (
    {"valor": "Dianteiro esquerdo", "eixo": EIXO_DIANTEIRO},
    {"valor": "Dianteiro direito", "eixo": EIXO_DIANTEIRO},

    {"valor": "Tração traseiro externo esquerdo", "eixo": EIXO_TRACAO},
    {"valor": "Tração traseiro interno esquerdo", "eixo": EIXO_TRACAO},
    {"valor": "Tração traseiro interno direito", "eixo": EIXO_TRACAO},
    {"valor": "Tração traseiro externo direito", "eixo": EIXO_TRACAO},

    {"valor": "Truck traseiro externo esquerdo", "eixo": EIXO_TRUCK},
    {"valor": "Truck traseiro interno esquerdo", "eixo": EIXO_TRUCK},
    {"valor": "Truck traseiro interno direito", "eixo": EIXO_TRUCK},
    {"valor": "Truck traseiro externo direito", "eixo": EIXO_TRUCK},

    {"valor": "Estepe", "eixo": EIXO_ESTEPE},
)

# Mantido para quem já importava esta constante.
POSICOES_CAMINHAO = tuple(p["valor"] for p in POSICOES)

# Nomes usados antes desta atualização. Continuam sendo aceitos na leitura
# dos registros antigos (o traseiro antigo era o eixo de tração), mas não
# aparecem mais na lista de escolha.
POSICOES_ANTIGAS = {
    "Dianteiro Esquerdo": "Dianteiro esquerdo",
    "Dianteiro Direito": "Dianteiro direito",
    "Traseiro Esquerdo Externo": "Tração traseiro externo esquerdo",
    "Traseiro Esquerdo Interno": "Tração traseiro interno esquerdo",
    "Traseiro Direito Externo": "Tração traseiro externo direito",
    "Traseiro Direito Interno": "Tração traseiro interno direito",
}


def _chave(texto) -> str:
    """Compara textos ignorando acento, maiúscula e espaço sobrando."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.lower().split())


_INDICE = {_chave(p["valor"]): p["valor"] for p in POSICOES}
for _antiga, _nova in POSICOES_ANTIGAS.items():
    _INDICE.setdefault(_chave(_antiga), _nova)


def normalizar_posicao(texto):
    """Devolve o valor oficial da posição, ou None se não reconhecer."""
    return _INDICE.get(_chave(texto))


def listar_posicoes():
    """Lista completa das posições, com o eixo de cada uma."""
    return [dict(p) for p in POSICOES]


def eh_item_pneu(item: ItemOS) -> bool:
    """Reconhece pneu pelo grupo e pela descrição do item ou da peça vinculada."""
    valores = [item.grupo, item.descricao]
    if item.peca is not None:
        valores.extend([item.peca.grupo, item.peca.descricao, item.peca.codigo])
    texto = " ".join(str(v or "") for v in valores).casefold()
    return "pneu" in texto


def _pneus_em_uso(veiculo_id):
    """Mapa {posicao_oficial: Pneu} dos pneus em uso no veículo."""
    ocupados = {}
    if not veiculo_id:
        return ocupados
    pneus = (Pneu.query
             .filter(Pneu.veiculo_id == veiculo_id, Pneu.status == "Em uso")
             .order_by(Pneu.id.desc()).all())
    for pneu in pneus:
        oficial = normalizar_posicao(pneu.posicao)
        if oficial and oficial not in ocupados:
            ocupados[oficial] = pneu
    return ocupados


def posicoes_do_veiculo(veiculo_id: int | None):
    ocupados = _pneus_em_uso(veiculo_id)

    retorno = []
    for posicao in POSICOES:
        nome = posicao["valor"]
        atual = ocupados.get(nome)
        retorno.append({
            "valor": nome,
            "eixo": posicao["eixo"],
            "ocupada": atual is not None,
            "pneu_atual_id": atual.id if atual else None,
            "pneu_atual": atual.numero_fogo if atual else None,
            "sulco_mm": atual.sulco_mm if atual else None,
        })
    return retorno


def montar_identificacao(posicao, numero_fogo=None):
    """Ex.: 'Pneu truck traseiro interno esquerdo — nº 3456'."""
    texto = f"Pneu {str(posicao).lower()}"
    if numero_fogo:
        texto += f" — nº {numero_fogo}"
    return texto


def _montar_descricao(base, identificacao):
    """Mantém a descrição da peça e acrescenta a identificação do pneu."""
    base = str(base or "").split(" · Pneu ")[0].strip()
    texto = f"{base} · {identificacao}" if base else identificacao
    return texto[:160]


def aplicar_posicao_pneu(item: ItemOS, posicao: str, numero_fogo: str | None = None):
    """Registra a posição e baixa o pneu antigo daquela posição.

    Não exclui registros. O pneu retirado permanece no banco como Descartado e
    o ItemOS mantém a referência em pneu_substituido_id. Quando o número de
    fogo é informado, o pneu novo entra em uso naquela posição.
    """
    valor = normalizar_posicao(posicao)
    if valor is None:
        raise ValueError("Posição de pneu inválida.")
    if not eh_item_pneu(item):
        raise ValueError("O item selecionado não foi identificado como pneu.")
    if item.ordem is None or item.ordem.veiculo_id is None:
        raise ValueError("A ordem de serviço precisa estar vinculada a um veículo.")

    # O fluxo de correção trabalha apenas com itens ainda sem posição. Isso
    # evita alterar uma substituição histórica já registrada.
    if item.posicao_pneu and normalizar_posicao(item.posicao_pneu) != valor:
        raise ValueError("Este pneu já possui posição registrada na ordem de serviço.")

    fogo = str(numero_fogo or "").strip()
    veiculo_id = item.ordem.veiculo_id

    # 1. Pneu que sai desta posição
    pneu_antigo = _pneus_em_uso(veiculo_id).get(valor)
    if pneu_antigo is not None and fogo and pneu_antigo.numero_fogo == fogo:
        # É o mesmo pneu: não há substituição a registrar.
        pneu_antigo = None

    if pneu_antigo is not None:
        item.pneu_substituido_id = pneu_antigo.id
        pneu_antigo.status = "Descartado"
        # Mantemos veículo e posição no histórico do pneu antigo.
        if pneu_antigo.data_medicao is None:
            pneu_antigo.data_medicao = hoje()

    # 2. Pneu que entra
    pneu_novo = None
    if fogo:
        pneu_novo = Pneu.query.filter(Pneu.numero_fogo == fogo).first()
        if pneu_novo is None:
            pneu_novo = Pneu(numero_fogo=fogo, vida="Novo", sulco_mm=0, custo=0)
            db.session.add(pneu_novo)
        pneu_novo.veiculo_id = veiculo_id
        pneu_novo.posicao = valor
        pneu_novo.status = "Em uso"
        pneu_novo.data_instalacao = hoje()
        pneu_novo.data_medicao = hoje()
        veiculo = db.session.get(Veiculo, veiculo_id)
        if veiculo is not None:
            pneu_novo.km_instalacao = veiculo.hodometro or 0

    # 3. Item da ordem de serviço
    identificacao = montar_identificacao(valor, fogo)
    item.posicao_pneu = valor
    item.descricao = _montar_descricao(item.descricao, identificacao)

    db.session.commit()

    return {
        "item_id": item.id,
        "ordem_servico_id": item.ordem_servico_id,
        "posicao": valor,
        "numero_fogo": fogo or None,
        "identificacao": identificacao,
        "descricao": item.descricao,
        "pneu_id": pneu_novo.id if pneu_novo else None,
        "pneu_substituido_id": pneu_antigo.id if pneu_antigo else None,
        "pneu_substituido": pneu_antigo.numero_fogo if pneu_antigo else None,
    }
