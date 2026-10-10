"""Posições de pneu por eixo e aplicação do pneu na ordem de serviço.

Substitui a lógica antiga de services/correcoes_os.py, acrescentando:
  * o EIXO TRUCK (2º eixo traseiro), além do dianteiro e do de tração;
  * o número de fogo do pneu no momento do lançamento, gerando a
    identificação completa no item da OS
    (ex.: "Pneu tração traseiro interno esquerdo — nº 3456").

Não exige migração: as colunas usadas (itens_os.posicao_pneu,
itens_os.pneu_substituido_id, pneus.numero_fogo, pneus.posicao) já existem.
"""
from __future__ import annotations

import unicodedata
from datetime import date

from extensions import db
from models import ItemOS, OrdemServico, Pneu, Veiculo

EIXO_DIANTEIRO = "Eixo dianteiro"
EIXO_TRACAO = "Eixo de tração"
EIXO_TRUCK = "Eixo truck"
EIXO_ESTEPE = "Estepe"

# Valor gravado no banco (máx. 40 caracteres) e o eixo a que pertence.
POSICOES = [
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
]

# Posições gravadas antes desta atualização continuam válidas para os
# registros antigos (elas não aparecem mais na lista de escolha).
POSICOES_ANTIGAS = {
    "traseiro esquerdo externo": "Tração traseiro externo esquerdo",
    "traseiro esquerdo interno": "Tração traseiro interno esquerdo",
    "traseiro direito interno": "Tração traseiro interno direito",
    "traseiro direito externo": "Tração traseiro externo direito",
}

ORDEM_EIXOS = [EIXO_DIANTEIRO, EIXO_TRACAO, EIXO_TRUCK, EIXO_ESTEPE]


def _sem_acento(texto: str) -> str:
    """Compara textos ignorando acento, maiúscula e espaço sobrando."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.lower().split())


_INDICE = {_sem_acento(p["valor"]): p["valor"] for p in POSICOES}
for _antiga, _nova in POSICOES_ANTIGAS.items():
    _INDICE.setdefault(_sem_acento(_antiga), _nova)


def normalizar_posicao(texto):
    """Devolve o valor oficial da posição, ou None se não reconhecer."""
    return _INDICE.get(_sem_acento(texto))


def listar_posicoes():
    """Lista completa das posições, agrupada por eixo."""
    return [dict(p) for p in POSICOES]


def eh_item_pneu(item) -> bool:
    """Diz se o item lançado na OS é um pneu."""
    if item is None:
        return False
    textos = [item.grupo, item.descricao]
    peca = getattr(item, "peca", None)
    if peca is not None:
        textos.extend([getattr(peca, "grupo", None),
                       getattr(peca, "descricao", None)])
    return any("pneu" in _sem_acento(t) for t in textos if t)


def _ordem_do_item(item):
    ordem = getattr(item, "ordem", None)
    if ordem is None and item.ordem_servico_id:
        ordem = db.session.get(OrdemServico, item.ordem_servico_id)
    return ordem


def _pneus_em_uso(veiculo_id):
    """Mapa {posicao_oficial: Pneu} dos pneus em uso no veículo."""
    if not veiculo_id:
        return {}
    mapa = {}
    consulta = Pneu.query.filter(Pneu.veiculo_id == veiculo_id,
                                 Pneu.status == "Em uso").all()
    for pneu in consulta:
        oficial = normalizar_posicao(pneu.posicao)
        if oficial:
            mapa[oficial] = pneu
    return mapa


def posicoes_do_veiculo(veiculo_id):
    """Posições disponíveis, já indicando qual pneu está em cada uma."""
    ocupadas = _pneus_em_uso(veiculo_id)
    resultado = []
    for posicao in POSICOES:
        pneu = ocupadas.get(posicao["valor"])
        resultado.append({
            "valor": posicao["valor"],
            "eixo": posicao["eixo"],
            "ocupada": pneu is not None,
            "pneu_atual": pneu.numero_fogo if pneu else None,
            "sulco_mm": pneu.sulco_mm if pneu else None,
        })
    return resultado


def montar_identificacao(posicao, numero_fogo=None):
    """Ex.: 'Pneu tração traseiro interno esquerdo — nº 3456'."""
    texto = f"Pneu {str(posicao).lower()}"
    if numero_fogo:
        texto += f" — nº {numero_fogo}"
    return texto


def _montar_descricao(base, identificacao):
    """Mantém a descrição da peça e acrescenta a identificação do pneu."""
    base = str(base or "").split(" · Pneu ")[0].strip()
    texto = f"{base} · {identificacao}" if base else identificacao
    return texto[:160]


def aplicar_posicao_pneu(item, posicao, numero_fogo=None):
    """Grava a posição (e o número de fogo) do pneu lançado na OS.

    O pneu que estava em uso naquela posição é marcado como Descartado e
    fica guardado em item.pneu_substituido_id, preservando o histórico.
    """
    if item is None:
        raise ValueError("Item da ordem de serviço não encontrado.")

    valor = normalizar_posicao(posicao)
    if not valor:
        raise ValueError("Selecione uma posição válida para o pneu.")

    fogo = str(numero_fogo or "").strip()

    ordem = _ordem_do_item(item)
    veiculo_id = ordem.veiculo_id if ordem else None
    veiculo = db.session.get(Veiculo, veiculo_id) if veiculo_id else None

    # 1. Pneu que sai desta posição
    substituido = _pneus_em_uso(veiculo_id).get(valor)
    if substituido is not None and (not fogo or substituido.numero_fogo != fogo):
        substituido.status = "Descartado"
        item.pneu_substituido_id = substituido.id
    else:
        substituido = None

    # 2. Pneu que entra
    novo = None
    if fogo:
        novo = Pneu.query.filter(Pneu.numero_fogo == fogo).first()
        if novo is None:
            novo = Pneu(numero_fogo=fogo, vida="Novo", sulco_mm=0, custo=0)
            db.session.add(novo)
        novo.veiculo_id = veiculo_id
        novo.posicao = valor
        novo.status = "Em uso"
        novo.data_instalacao = date.today()
        novo.data_medicao = date.today()
        if veiculo is not None:
            novo.km_instalacao = veiculo.hodometro or 0

    # 3. Item da OS
    identificacao = montar_identificacao(valor, fogo)
    item.posicao_pneu = valor
    item.descricao = _montar_descricao(item.descricao, identificacao)

    db.session.commit()

    return {
        "posicao": valor,
        "numero_fogo": fogo or None,
        "identificacao": identificacao,
        "descricao": item.descricao,
        "pneu_substituido": substituido.numero_fogo if substituido else None,
        "pneu_id": novo.id if novo else None,
    }
