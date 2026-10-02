"""Estoque físico de combustível por NF e baixa automática por abastecimento.

O controle passa a valer, para cada produto, a partir da primeira NF registrada.
Abastecimentos anteriores permanecem históricos e não são retroativamente bloqueados.
"""
from collections import defaultdict
from datetime import date

from extensions import db
from models import Abastecimento, ControleEstoqueCombustivel, NotaFiscalCombustivel
from services.crud import ErroNegocio

EPS = 1e-6


def _normalizar_combustivel(valor):
    return (valor or "Diesel S10").strip() or "Diesel S10"


def _config(combustivel):
    return ControleEstoqueCombustivel.query.filter_by(
        combustivel=_normalizar_combustivel(combustivel)).first()


def ativar_controle(combustivel, data_inicio):
    combustivel = _normalizar_combustivel(combustivel)
    cfg = _config(combustivel)
    if not cfg:
        cfg = ControleEstoqueCombustivel(combustivel=combustivel, data_inicio=data_inicio)
        db.session.add(cfg)
        db.session.flush()
    elif data_inicio and data_inicio < cfg.data_inicio:
        # Uma NF retroativa passa a ser a primeira entrada controlada.
        cfg.data_inicio = data_inicio
        db.session.flush()
    return cfg


def _eventos(combustivel):
    combustivel = _normalizar_combustivel(combustivel)
    cfg = _config(combustivel)
    if not cfg:
        return None, []

    entradas = (NotaFiscalCombustivel.query
                .filter(NotaFiscalCombustivel.combustivel == combustivel,
                        NotaFiscalCombustivel.data >= cfg.data_inicio)
                .all())
    saidas = (Abastecimento.query
              .filter(Abastecimento.combustivel == combustivel,
                      Abastecimento.data >= cfg.data_inicio)
              .all())

    eventos = []
    for n in entradas:
        eventos.append((n.data, 0, n.id or 0, "entrada", n))
    for a in saidas:
        eventos.append((a.data, 1, a.id or 0, "saida", a))
    eventos.sort(key=lambda x: (x[0] or date.min, x[1], x[2]))
    return cfg, eventos


def recalcular_estoque_combustivel(combustivel, validar=True):
    """Reprocessa o kardex cronologicamente e atualiza o custo médio das saídas."""
    combustivel = _normalizar_combustivel(combustivel)
    cfg, eventos = _eventos(combustivel)
    if not cfg:
        return {
            "combustivel": combustivel, "ativo": False, "data_inicio": None,
            "litros_estoque": 0, "valor_estoque": 0, "custo_medio": 0,
            "litros_comprados": 0, "valor_comprado": 0,
            "litros_consumidos": 0, "valor_consumido": 0, "movimentacoes": []
        }

    saldo_litros = 0.0
    saldo_valor = 0.0
    litros_comprados = valor_comprado = 0.0
    litros_consumidos = valor_consumido = 0.0
    movimentos = []

    from services.calculos import recalcular_abastecimento

    for data_mov, _prioridade, _id, tipo, obj in eventos:
        if tipo == "entrada":
            litros = float(obj.litros or 0)
            if litros <= 0:
                if validar:
                    raise ErroNegocio(f"A NF {obj.numero_nf} precisa ter quantidade de litros maior que zero.")
                continue
            total = float(obj.valor_total or 0)
            unit = float(obj.valor_litro or 0)
            if total <= 0 and unit > 0:
                total = round(litros * unit, 2)
                obj.valor_total = total
            elif unit <= 0 and total > 0:
                unit = total / litros
                obj.valor_litro = round(unit, 4)
            if total <= 0:
                if validar:
                    raise ErroNegocio(f"Informe o valor da NF {obj.numero_nf}.")
                continue
            saldo_litros += litros
            saldo_valor += total
            litros_comprados += litros
            valor_comprado += total
            custo_medio = saldo_valor / saldo_litros if saldo_litros else 0
            movimentos.append({
                "data": data_mov.isoformat(), "tipo": "Entrada NF",
                "documento": f"NF {obj.numero_nf}", "referencia_id": obj.id,
                "combustivel": combustivel, "litros": round(litros, 3),
                "entrada": round(litros, 3), "saida": 0,
                "valor_unitario": round(total / litros, 4),
                "valor": round(total, 2), "saldo_litros": round(saldo_litros, 3),
                "saldo_valor": round(saldo_valor, 2), "custo_medio": round(custo_medio, 4),
            })
        else:
            litros = float(obj.litros or 0)
            if litros <= 0:
                continue
            if saldo_litros + EPS < litros:
                frota = obj.veiculo.prefixo if obj.veiculo else str(obj.veiculo_id or "—")
                faltam = litros - saldo_litros
                raise ErroNegocio(
                    f"Estoque insuficiente de {combustivel} em {data_mov.strftime('%d/%m/%Y')}. "
                    f"Frota {frota}: solicitado {litros:.2f} L, disponível {max(saldo_litros, 0):.2f} L "
                    f"(faltam {faltam:.2f} L). Lance uma NF de entrada antes do abastecimento.")
            custo_medio = saldo_valor / saldo_litros if saldo_litros else 0
            custo_saida = litros * custo_medio
            obj.valor_litro = round(custo_medio, 4)
            obj.valor_total = round(custo_saida, 2)
            recalcular_abastecimento(obj)
            saldo_litros -= litros
            saldo_valor -= custo_saida
            if abs(saldo_litros) < EPS:
                saldo_litros = 0.0
                saldo_valor = 0.0
            litros_consumidos += litros
            valor_consumido += custo_saida
            movimentos.append({
                "data": data_mov.isoformat(), "tipo": "Saída abastecimento",
                "documento": f"Frota {obj.veiculo.prefixo if obj.veiculo else obj.veiculo_id}",
                "referencia_id": obj.id, "combustivel": combustivel,
                "litros": round(litros, 3), "entrada": 0, "saida": round(litros, 3),
                "valor_unitario": round(custo_medio, 4), "valor": round(custo_saida, 2),
                "saldo_litros": round(saldo_litros, 3), "saldo_valor": round(saldo_valor, 2),
                "custo_medio": round((saldo_valor / saldo_litros) if saldo_litros else 0, 4),
            })

    custo_medio = saldo_valor / saldo_litros if saldo_litros else 0
    return {
        "combustivel": combustivel, "ativo": True,
        "data_inicio": cfg.data_inicio.isoformat() if cfg.data_inicio else None,
        "litros_estoque": round(saldo_litros, 3),
        "valor_estoque": round(saldo_valor, 2),
        "custo_medio": round(custo_medio, 4),
        "litros_comprados": round(litros_comprados, 3),
        "valor_comprado": round(valor_comprado, 2),
        "litros_consumidos": round(litros_consumidos, 3),
        "valor_consumido": round(valor_consumido, 2),
        "movimentacoes": movimentos,
    }


def recalcular_todos_combustiveis():
    resultados = []
    for cfg in ControleEstoqueCombustivel.query.order_by(ControleEstoqueCombustivel.combustivel).all():
        resultados.append(recalcular_estoque_combustivel(cfg.combustivel))
    db.session.flush()
    return resultados


def resumo_geral():
    itens = recalcular_todos_combustiveis()
    return {
        "itens": itens,
        "litros_estoque": round(sum(x["litros_estoque"] for x in itens), 3),
        "valor_estoque": round(sum(x["valor_estoque"] for x in itens), 2),
        "litros_comprados": round(sum(x["litros_comprados"] for x in itens), 3),
        "valor_comprado": round(sum(x["valor_comprado"] for x in itens), 2),
        "litros_consumidos": round(sum(x["litros_consumidos"] for x in itens), 3),
        "valor_consumido": round(sum(x["valor_consumido"] for x in itens), 2),
    }


def movimentacoes(inicio=None, fim=None):
    linhas = []
    for item in recalcular_todos_combustiveis():
        for mov in item["movimentacoes"]:
            d = date.fromisoformat(mov["data"])
            if inicio and d < inicio:
                continue
            if fim and d > fim:
                continue
            linhas.append(mov)
    linhas.sort(key=lambda x: (x["data"], 0 if x["tipo"].startswith("Entrada") else 1, x["referencia_id"]))
    return linhas
