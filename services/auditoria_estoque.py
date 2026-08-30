"""Auditoria e regularização de baixa de estoque em OS finalizadas."""
from collections import defaultdict

from extensions import db
from models import ItemOS, OrdemServico, Peca
from services.calculos import baixar_item_os
from services.crud import ErroNegocio


def _itens_pendentes(ordem):
    return [
        item for item in ordem.itens
        if item.peca_id and not item.baixado_estoque
    ]


def _necessidades_por_peca(itens):
    necessidades = defaultdict(float)
    for item in itens:
        necessidades[item.peca_id] += float(item.quantidade or 0)
    return necessidades


def _avaliar_ordem(ordem):
    itens = _itens_pendentes(ordem)
    necessidades = _necessidades_por_peca(itens)
    saldos = {}
    insuficientes = []

    for peca_id, quantidade in necessidades.items():
        peca = db.session.get(Peca, peca_id)
        saldo = float(peca.quantidade or 0) if peca else 0.0
        saldos[peca_id] = saldo
        if quantidade <= 0:
            insuficientes.append({
                "peca_id": peca_id,
                "codigo": peca.codigo if peca else "",
                "descricao": peca.descricao if peca else "Peça não encontrada",
                "necessario": quantidade,
                "disponivel": saldo,
                "motivo": "Quantidade inválida na OS",
            })
        elif not peca or saldo < quantidade:
            insuficientes.append({
                "peca_id": peca_id,
                "codigo": peca.codigo if peca else "",
                "descricao": peca.descricao if peca else "Peça não encontrada",
                "necessario": quantidade,
                "disponivel": saldo,
                "motivo": "Estoque insuficiente",
            })

    itens_dados = []
    for item in itens:
        peca = item.peca
        necessario_total = necessidades.get(item.peca_id, 0.0)
        saldo = saldos.get(item.peca_id, 0.0)
        itens_dados.append({
            "id": item.id,
            "peca_id": item.peca_id,
            "codigo": peca.codigo if peca else "",
            "descricao": item.descricao or (peca.descricao if peca else "Peça não encontrada"),
            "quantidade": float(item.quantidade or 0),
            "unidade": peca.unidade if peca else "",
            "estoque_atual": saldo,
            "necessario_total_peca": necessario_total,
            "suficiente": bool(peca) and necessario_total > 0 and saldo >= necessario_total,
        })

    return {
        "id": ordem.id,
        "numero": ordem.numero,
        "data_abertura": ordem.data_abertura.isoformat() if ordem.data_abertura else None,
        "data_fechamento": ordem.data_fechamento.isoformat() if ordem.data_fechamento else None,
        "veiculo_id": ordem.veiculo_id,
        "veiculo_nome": (
            f"{ordem.veiculo.prefixo} · {ordem.veiculo.placa}"
            if ordem.veiculo else None
        ),
        "itens_pendentes": len(itens),
        "itens": itens_dados,
        "insuficientes": insuficientes,
        "pode_regularizar": bool(itens) and not insuficientes,
    }


def listar_pendencias():
    ordens = (
        OrdemServico.query
        .join(ItemOS, ItemOS.ordem_servico_id == OrdemServico.id)
        .filter(
            OrdemServico.status == "Finalizada",
            ItemOS.peca_id.is_not(None),
            ItemOS.baixado_estoque.is_not(True),
        )
        .distinct()
        .order_by(OrdemServico.data_fechamento.desc(), OrdemServico.id.desc())
        .all()
    )
    return [_avaliar_ordem(ordem) for ordem in ordens]


def resumir_pendencias(ordens=None):
    ordens = listar_pendencias() if ordens is None else ordens
    return {
        "total_os": len(ordens),
        "total_itens": sum(o["itens_pendentes"] for o in ordens),
        "podem_regularizar": sum(1 for o in ordens if o["pode_regularizar"]),
        "aguardando_estoque": sum(1 for o in ordens if not o["pode_regularizar"]),
    }


def contar_os_pendentes():
    return (
        db.session.query(OrdemServico.id)
        .join(ItemOS, ItemOS.ordem_servico_id == OrdemServico.id)
        .filter(
            OrdemServico.status == "Finalizada",
            ItemOS.peca_id.is_not(None),
            ItemOS.baixado_estoque.is_not(True),
        )
        .distinct()
        .count()
    )


def regularizar_os(os_id):
    ordem = db.session.get(OrdemServico, os_id)
    if not ordem:
        raise ErroNegocio("Ordem de serviço não encontrada.")
    if ordem.status != "Finalizada":
        raise ErroNegocio("Somente uma OS finalizada pode ser regularizada por esta tela.")

    avaliacao = _avaliar_ordem(ordem)
    if not avaliacao["itens"]:
        raise ErroNegocio("Esta OS não possui baixa de estoque pendente.")

    if avaliacao["insuficientes"]:
        faltas = []
        for item in avaliacao["insuficientes"]:
            codigo = item["codigo"] or item["descricao"]
            faltas.append(
                f"{codigo}: necessário {item['necessario']:g}, disponível {item['disponivel']:g}"
            )
        raise ErroNegocio("Estoque insuficiente para regularizar esta OS. " + "; ".join(faltas))

    itens = _itens_pendentes(ordem)
    for item in itens:
        baixar_item_os(item)

    return ordem, len(itens)
