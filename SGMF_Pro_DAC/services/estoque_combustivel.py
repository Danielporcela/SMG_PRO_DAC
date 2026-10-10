"""Estoque físico de combustível por NF e baixa automática por abastecimento.

O controle passa a valer, para cada produto, a partir da primeira NF registrada.
Abastecimentos anteriores permanecem históricos e não são retroativamente bloqueados.
"""
from collections import defaultdict
from datetime import date

from extensions import db
from models import (Abastecimento, AjusteEstoqueCombustivel,
                    ControleEstoqueCombustivel, NotaFiscalCombustivel)
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

    # A data fiscal e a data física de entrada podem ser diferentes. O kardex
    # usa SEMPRE a data física; para registros antigos, cai para a data da NF.
    todas_entradas = (NotaFiscalCombustivel.query
                      .filter(NotaFiscalCombustivel.combustivel == combustivel)
                      .all())
    entradas = [n for n in todas_entradas
                if (n.data_entrada or n.data) and (n.data_entrada or n.data) >= cfg.data_inicio]
    ajustes = (AjusteEstoqueCombustivel.query
               .filter(AjusteEstoqueCombustivel.combustivel == combustivel,
                       AjusteEstoqueCombustivel.data >= cfg.data_inicio)
               .all())
    saidas = (Abastecimento.query
              .filter(Abastecimento.combustivel == combustivel,
                      Abastecimento.data >= cfg.data_inicio)
              .all())

    eventos = []
    for n in entradas:
        eventos.append(((n.data_entrada or n.data), 0, n.id or 0, "entrada", n))
    # O ajuste físico representa o saldo conferido ao FINAL do dia.
    # Portanto, no mesmo dia ele deve ser processado depois das NFs e
    # dos abastecimentos; caso contrário, a diferença calculada sobre o
    # saldo final seria aplicada antes das saídas e poderia gerar
    # artificialmente "estoque insuficiente".
    for a in saidas:
        eventos.append((a.data, 1, a.id or 0, "saida", a))
    for aj in ajustes:
        eventos.append((aj.data, 2, aj.id or 0, "ajuste", aj))
    eventos.sort(key=lambda x: (x[0] or date.min, x[1], x[2]))
    return cfg, eventos


def recalcular_estoque_combustivel(combustivel, validar=True, estrito=True):
    """Reprocessa o kardex cronologicamente e atualiza o custo médio das saídas.

    estrito=True  (padrão): saldo insuficiente levanta ErroNegocio. É o que
                  protege gravações (NF, abastecimento, importação).
    estrito=False: usado nas CONSULTAS (tela/botão "Atualizar estoque"). Não
                  levanta erro; registra o problema em "alertas" e segue, para
                  uma inconsistência antiga não travar a tela inteira.
    """
    combustivel = _normalizar_combustivel(combustivel)
    cfg, eventos = _eventos(combustivel)
    if not cfg:
        return {
            "combustivel": combustivel, "ativo": False, "data_inicio": None,
            "litros_estoque": 0, "valor_estoque": 0, "custo_medio": 0,
            "litros_comprados": 0, "valor_comprado": 0,
            "litros_consumidos": 0, "valor_consumido": 0, "movimentacoes": [],
            "alertas": []
        }

    saldo_litros = 0.0
    saldo_valor = 0.0
    litros_comprados = valor_comprado = 0.0
    litros_consumidos = valor_consumido = 0.0
    movimentos = []
    alertas = []
    ultimo_custo = 0.0

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
            ultimo_custo = custo_medio
            movimentos.append({
                "data": data_mov.isoformat(), "tipo": "Entrada NF",
                "documento": f"NF {obj.numero_nf}", "referencia_id": obj.id,
                "combustivel": combustivel, "litros": round(litros, 3),
                "entrada": round(litros, 3), "saida": 0,
                "valor_unitario": round(total / litros, 4),
                "valor": round(total, 2), "saldo_litros": round(saldo_litros, 3),
                "saldo_valor": round(saldo_valor, 2), "custo_medio": round(custo_medio, 4),
                "alerta": None,
            })
        elif tipo == "ajuste":
            # Ajustes novos representam uma CONFERÊNCIA FÍSICA do tanque ao
            # final da data. A fonte da verdade é ``saldo_fisico``; o delta
            # é recalculado toda vez que o kardex é reprocessado. Isso permite
            # lançar/editar NFs retroativas sem tornar o ajuste inválido.
            alvo = getattr(obj, "saldo_fisico", None)
            custo_ref = float(obj.valor_unitario or 0)
            if custo_ref <= 0:
                custo_ref = (saldo_valor / saldo_litros) if saldo_litros > EPS else ultimo_custo

            if alvo is not None:
                alvo = max(float(alvo), 0.0)
                delta = alvo - saldo_litros
                # Mantém o campo legado sincronizado apenas para exibição e
                # auditoria; ele não dirige mais o saldo do estoque.
                obj.litros = round(delta, 3)
                if abs(delta) < EPS:
                    continue
            else:
                # Compatibilidade com ajustes antigos que ainda só têm delta.
                delta = float(obj.litros or 0)
                if abs(delta) < EPS:
                    continue
                # Se um ajuste legado tenta retirar mais do que havia naquele
                # ponto do histórico, ele é inconsistente. Não deve impedir
                # novas NFs ou abastecimentos de serem gravados. Ignoramos o
                # lançamento legado e sinalizamos para que o operador faça uma
                # nova conferência física pelo botão Ajustar estoque.
                if delta < 0 and saldo_litros + EPS < abs(delta):
                    aviso = (
                        f"Ajuste legado inconsistente de {combustivel} em "
                        f"{data_mov.strftime('%d/%m/%Y')}: retirada gravada de "
                        f"{abs(delta):.2f} L para saldo disponível de "
                        f"{max(saldo_litros, 0):.2f} L. O ajuste foi ignorado; "
                        f"faça uma nova conferência física do estoque.")
                    alertas.append(aviso)
                    movimentos.append({
                        "data": data_mov.isoformat(), "tipo": "Ajuste legado ignorado",
                        "documento": f"Ajuste #{obj.id} · {obj.motivo}",
                        "referencia_id": obj.id, "combustivel": combustivel,
                        "litros": round(abs(delta), 3), "entrada": 0, "saida": 0,
                        "valor_unitario": round(custo_ref, 4), "valor": 0,
                        "saldo_litros": round(saldo_litros, 3),
                        "saldo_valor": round(saldo_valor, 2),
                        "custo_medio": round((saldo_valor / saldo_litros) if saldo_litros else 0, 4),
                        "alerta": aviso, "usuario": obj.usuario,
                    })
                    continue

            valor_delta = abs(delta) * custo_ref
            if delta > 0:
                saldo_litros += delta
                saldo_valor += valor_delta
                entrada, saida = delta, 0.0
                tipo_mov = "Ajuste positivo"
            else:
                retirar = abs(delta)
                # Para ajuste por saldo físico, retirar nunca será maior que o
                # saldo naquele ponto, pois delta = alvo - saldo_atual e alvo >= 0.
                # Esta checagem fica como proteção adicional para dados legados.
                if saldo_litros + EPS < retirar:
                    aviso = (f"Ajuste de estoque insuficiente de {combustivel} em "
                             f"{data_mov.strftime('%d/%m/%Y')}: tentativa de retirar "
                             f"{retirar:.2f} L com saldo de {max(saldo_litros, 0):.2f} L.")
                    alertas.append(aviso)
                    retirar = max(saldo_litros, 0)
                    valor_delta = retirar * custo_ref
                saldo_litros -= retirar
                saldo_valor -= valor_delta
                if saldo_litros < EPS:
                    saldo_litros = 0.0
                    saldo_valor = 0.0
                entrada, saida = 0.0, retirar
                tipo_mov = "Ajuste negativo"
            ultimo_custo = (saldo_valor / saldo_litros) if saldo_litros > EPS else custo_ref
            movimentos.append({
                "data": data_mov.isoformat(), "tipo": tipo_mov,
                "documento": f"Ajuste #{obj.id} · {obj.motivo}", "referencia_id": obj.id,
                "combustivel": combustivel, "litros": round(abs(delta), 3),
                "entrada": round(entrada, 3), "saida": round(saida, 3),
                "valor_unitario": round(custo_ref, 4), "valor": round(valor_delta, 2),
                "saldo_litros": round(saldo_litros, 3), "saldo_valor": round(saldo_valor, 2),
                "custo_medio": round((saldo_valor / saldo_litros) if saldo_litros else 0, 4),
                "alerta": None, "usuario": obj.usuario,
            })
        else:
            litros = float(obj.litros or 0)
            if litros <= 0:
                continue
            sem_saldo = saldo_litros + EPS < litros
            aviso = None
            if sem_saldo:
                frota = obj.veiculo.prefixo if obj.veiculo else str(obj.veiculo_id or "—")
                faltam = litros - saldo_litros
                aviso = (
                    f"Estoque insuficiente de {combustivel} em {data_mov.strftime('%d/%m/%Y')}. "
                    f"Frota {frota}: solicitado {litros:.2f} L, disponível {max(saldo_litros, 0):.2f} L "
                    f"(faltam {faltam:.2f} L). Lance uma NF de entrada antes do abastecimento.")
                if estrito:
                    raise ErroNegocio(aviso)
                alertas.append(aviso)
            # Sem saldo (só no modo não estrito): valoriza pelo último custo médio conhecido.
            custo_medio = saldo_valor / saldo_litros if saldo_litros > EPS else ultimo_custo
            custo_saida = litros * custo_medio
            obj.valor_litro = round(custo_medio, 4)
            obj.valor_total = round(custo_saida, 2)
            recalcular_abastecimento(obj)
            if sem_saldo:
                # Não deixa o saldo ficar negativo: o que faltou fica sinalizado no alerta.
                saldo_litros = 0.0
                saldo_valor = 0.0
            else:
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
                "alerta": aviso,
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
        "alertas": alertas,
    }


def recalcular_todos_combustiveis(estrito=True):
    resultados = []
    for cfg in ControleEstoqueCombustivel.query.order_by(ControleEstoqueCombustivel.combustivel).all():
        resultados.append(recalcular_estoque_combustivel(cfg.combustivel, estrito=estrito))
    db.session.flush()
    return resultados


def resumo_geral(estrito=True):
    itens = recalcular_todos_combustiveis(estrito)
    return {
        "itens": itens,
        "alertas": [a for x in itens for a in x.get("alertas", [])],
        "litros_estoque": round(sum(x["litros_estoque"] for x in itens), 3),
        "valor_estoque": round(sum(x["valor_estoque"] for x in itens), 2),
        "litros_comprados": round(sum(x["litros_comprados"] for x in itens), 3),
        "valor_comprado": round(sum(x["valor_comprado"] for x in itens), 2),
        "litros_consumidos": round(sum(x["litros_consumidos"] for x in itens), 3),
        "valor_consumido": round(sum(x["valor_consumido"] for x in itens), 2),
    }


def movimentacoes(inicio=None, fim=None, estrito=True):
    linhas = []
    for item in recalcular_todos_combustiveis(estrito):
        for mov in item["movimentacoes"]:
            d = date.fromisoformat(mov["data"])
            if inicio and d < inicio:
                continue
            if fim and d > fim:
                continue
            linhas.append(mov)
    linhas.sort(key=lambda x: (x["data"], 0 if x["tipo"].startswith("Entrada") else (1 if x["tipo"].startswith("Ajuste") else 2), x["referencia_id"]))
    return linhas
