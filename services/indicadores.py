"""KPIs do painel executivo, rankings e alertas automáticos."""
import calendar
from datetime import date, timedelta

from flask import current_app
from sqlalchemy import func

from extensions import db
from models import Abastecimento, ItemOS, OrdemServico, Orcamento, Peca, Pneu, Veiculo
from services.tempo import hoje as data_de_hoje

GRUPOS = ["Motor", "Suspensão", "Freios", "Elétrica", "Hidráulica", "Pneus",
          "Transmissão", "Arrefecimento", "Outros"]
MESES = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def periodo_padrao(inicio=None, fim=None):
    hoje = data_de_hoje()
    fim = date.fromisoformat(fim) if fim else hoje
    inicio = date.fromisoformat(inicio) if inicio else hoje - timedelta(days=29)
    return inicio, fim


def _custo_os(inicio, fim, veiculo_id=None):
    """Custo total de manutenção (peças + mão de obra + serviços) no período."""
    q = OrdemServico.query.filter(OrdemServico.data_abertura.between(inicio, fim))
    if veiculo_id:
        q = q.filter(OrdemServico.veiculo_id == veiculo_id)
    return q.all()


def _custo_km_historico(ate, veiculo_id=None):
    """Custo por km da frota antes do período — a régua da comparação."""
    q_ab = Abastecimento.query.filter(Abastecimento.data < ate)
    q_os = OrdemServico.query.filter(OrdemServico.data_abertura < ate)
    if veiculo_id:
        q_ab = q_ab.filter(Abastecimento.veiculo_id == veiculo_id)
        q_os = q_os.filter(OrdemServico.veiculo_id == veiculo_id)

    abastecimentos = q_ab.all()
    km = sum(a.km_percorridos or 0 for a in abastecimentos)
    if km < 500:            # histórico curto demais para servir de referência
        return None
    gasto = (sum(a.valor_total or 0 for a in abastecimentos)
             + sum(o.custo_total for o in q_os.all()))
    return round(gasto / km, 4)


def prazo_medio_atendimento(ordens):
    """Dias entre a abertura e o fechamento das OS concluídas no período."""
    fechadas = [o for o in ordens if o.status == "Finalizada" and o.data_fechamento
                and o.data_abertura]
    if not fechadas:
        return None
    dias = sum((o.data_fechamento - o.data_abertura).days for o in fechadas)
    return round(dias / len(fechadas), 1)


def resumo(inicio=None, fim=None, veiculo_id=None):
    inicio, fim = periodo_padrao(inicio, fim)
    ordens = _custo_os(inicio, fim, veiculo_id)

    q_ab = Abastecimento.query.filter(Abastecimento.data.between(inicio, fim))
    if veiculo_id:
        q_ab = q_ab.filter(Abastecimento.veiculo_id == veiculo_id)
    abastecimentos = q_ab.all()

    veiculos = Veiculo.query.filter_by(ativo=True)
    if veiculo_id:
        veiculos = veiculos.filter(Veiculo.id == veiculo_id)
    veiculos = veiculos.all()
    total_veic = len(veiculos) or 1

    gasto_manut = round(sum(o.custo_total for o in ordens), 2)
    gasto_comb = round(sum(a.valor_total or 0 for a in abastecimentos), 2)
    litros = sum(a.litros or 0 for a in abastecimentos)
    km_rodados = sum(a.km_percorridos or 0 for a in abastecimentos)

    finalizadas = [o for o in ordens if o.status == "Finalizada" and o.data_fechamento]
    corretivas = [o for o in ordens if o.tipo in ("Corretiva", "Emergencial")]
    dias_periodo = max((fim - inicio).days + 1, 1)
    horas_paradas = sum(o.dias_parado * 24 for o in ordens)
    horas_disponiveis = total_veic * dias_periodo * 24

    mttr = round(sum(o.dias_parado for o in finalizadas) / len(finalizadas), 1) if finalizadas else 0
    mtbf = round((total_veic * dias_periodo) / len(corretivas), 1) if corretivas else 0

    orcado = db.session.query(func.sum(Orcamento.meta_valor)).filter(
        Orcamento.ano == fim.year, Orcamento.mes == fim.month).scalar() or 0

    # Economia do período: quanto o custo por km atual está melhor (ou pior)
    # que a média histórica, aplicado aos km rodados agora.
    custo_km_atual = round((gasto_comb + gasto_manut) / km_rodados, 4) if km_rodados else 0
    referencia = _custo_km_historico(inicio, veiculo_id)
    if referencia and km_rodados:
        economia = round((referencia - custo_km_atual) * km_rodados, 2)
        variacao = round((custo_km_atual - referencia) / referencia * 100, 1)
    else:
        economia, variacao = None, None

    prazo_medio = prazo_medio_atendimento(ordens)

    return {
        "periodo": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "veiculos_total": len(veiculos),
        "veiculos_manutencao": sum(1 for v in veiculos if v.situacao == "Em manutenção"),
        "veiculos_disponiveis": sum(1 for v in veiculos if v.situacao == "Disponível"),
        "abastecimentos": len(abastecimentos),
        "litros": round(litros, 1),
        "gasto_combustivel": gasto_comb,
        "gasto_manutencao": gasto_manut,
        "gasto_total": round(gasto_comb + gasto_manut, 2),
        "km_rodados": round(km_rodados),
        "consumo_medio": round(km_rodados / litros, 2) if litros else 0,
        "custo_por_km": round((gasto_comb + gasto_manut) / km_rodados, 2) if km_rodados else 0,
        "disponibilidade": round(max(0, (horas_disponiveis - horas_paradas)) / horas_disponiveis * 100, 1)
        if horas_disponiveis else 100,
        "mttr_dias": mttr,
        "mtbf_dias": mtbf,
        "economia_periodo": economia,
        "custo_km_historico": referencia,
        "variacao_custo_km": variacao,
        "prazo_medio_atendimento": prazo_medio,
        "os_finalizadas": sum(1 for o in ordens if o.status == "Finalizada"),
        "os_abertas": sum(1 for o in ordens if o.status != "Finalizada"),
        "os_preventivas": sum(1 for o in ordens if o.tipo == "Preventiva"),
        "os_corretivas": len(corretivas),
        "orcamento_mes": round(orcado, 2),
        "aderencia_orcamento": round((gasto_comb + gasto_manut) / orcado * 100, 1) if orcado else 0,
        "estoque_valor": round(sum((p.quantidade or 0) * (p.custo_unitario or 0)
                                   for p in Peca.query.all()), 2),
        "estoque_critico": Peca.query.filter(Peca.quantidade <= Peca.estoque_minimo).count(),
    }


def series_graficos(inicio=None, fim=None):
    """Dados dos gráficos do dashboard (módulos 6, 8 e 9)."""
    inicio, fim = periodo_padrao(inicio, fim)
    hoje = data_de_hoje()

    # 12 meses móveis de gasto
    meses, comb_mes, manut_mes, meta_mes = [], [], [], []
    for i in range(11, -1, -1):
        ref = (hoje.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        ini = ref
        f = ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
        meses.append(f"{MESES[ref.month - 1]}/{str(ref.year)[2:]}")
        comb_mes.append(round(db.session.query(func.sum(Abastecimento.valor_total))
                              .filter(Abastecimento.data.between(ini, f)).scalar() or 0, 2))
        ordens = OrdemServico.query.filter(OrdemServico.data_abertura.between(ini, f)).all()
        manut_mes.append(round(sum(o.custo_total for o in ordens), 2))
        meta_mes.append(round(db.session.query(func.sum(Orcamento.meta_valor))
                              .filter(Orcamento.ano == ref.year, Orcamento.mes == ref.month)
                              .scalar() or 0, 2))

    # custo por veículo no período
    por_veiculo = []
    for v in Veiculo.query.filter_by(ativo=True).all():
        ordens = OrdemServico.query.filter(OrdemServico.veiculo_id == v.id,
                                           OrdemServico.data_abertura.between(inicio, fim)).all()
        comb = db.session.query(func.sum(Abastecimento.valor_total)).filter(
            Abastecimento.veiculo_id == v.id,
            Abastecimento.data.between(inicio, fim)).scalar() or 0
        km = db.session.query(func.sum(Abastecimento.km_percorridos)).filter(
            Abastecimento.veiculo_id == v.id,
            Abastecimento.data.between(inicio, fim)).scalar() or 0
        litros = db.session.query(func.sum(Abastecimento.litros)).filter(
            Abastecimento.veiculo_id == v.id,
            Abastecimento.data.between(inicio, fim)).scalar() or 0
        total = round(sum(o.custo_total for o in ordens) + comb, 2)
        por_veiculo.append({
            "veiculo": v.prefixo, "placa": v.placa, "manutencao": round(sum(o.custo_total for o in ordens), 2),
            "combustivel": round(comb, 2), "total": total, "km": round(km),
            "consumo": round(km / litros, 2) if litros else 0,
            "custo_km": round(total / km, 2) if km else 0,
            "orcamento": v.orcamento_mensal or 0,
        })
    por_veiculo.sort(key=lambda x: x["total"], reverse=True)

    # custo por grupo de peças
    grupos = {}
    for item in (db.session.query(ItemOS).join(OrdemServico)
                 .filter(OrdemServico.data_abertura.between(inicio, fim)).all()):
        chave = item.grupo or (item.peca.grupo if item.peca else None) or "Outros"
        grupos[chave] = round(grupos.get(chave, 0) + (item.quantidade or 0) * (item.valor_unitario or 0), 2)

    ordens_periodo = OrdemServico.query.filter(
        OrdemServico.data_abertura.between(inicio, fim)).all()
    tipos = {"Preventiva": 0, "Corretiva": 0, "Emergencial": 0}
    for o in ordens_periodo:
        tipos[o.tipo] = tipos.get(o.tipo, 0) + 1

    return {
        "meses": meses, "combustivel_mes": comb_mes, "manutencao_mes": manut_mes,
        "meta_mes": meta_mes,
        "realizado_mes": [round(c + m, 2) for c, m in zip(comb_mes, manut_mes)],
        "por_veiculo": por_veiculo[:10],
        "grupos": {"labels": list(grupos.keys()), "valores": list(grupos.values())},
        "tipos_manutencao": tipos,
        "consumo_veiculo": sorted(
            [{"veiculo": v["veiculo"], "consumo": v["consumo"]} for v in por_veiculo if v["consumo"]],
            key=lambda x: x["consumo"], reverse=True)[:10],
    }


def rankings(inicio=None, fim=None):
    """Módulo 10 — rankings de motoristas e veículos."""
    inicio, fim = periodo_padrao(inicio, fim)

    motoristas = {}
    for a in Abastecimento.query.filter(Abastecimento.data.between(inicio, fim)).all():
        if not a.motorista_id:
            continue
        m = motoristas.setdefault(a.motorista_id, {
            "nome": a.motorista.nome if a.motorista else "—",
            "litros": 0, "km": 0, "custo": 0, "abastecimentos": 0})
        m["litros"] += a.litros or 0
        m["km"] += a.km_percorridos or 0
        m["custo"] += a.valor_total or 0
        m["abastecimentos"] += 1
    lista_mot = []
    for m in motoristas.values():
        lista_mot.append({**m,
                          "consumo": round(m["km"] / m["litros"], 2) if m["litros"] else 0,
                          "custo_km": round(m["custo"] / m["km"], 2) if m["km"] else 0,
                          "km": round(m["km"]), "litros": round(m["litros"], 1),
                          "custo": round(m["custo"], 2)})

    dados = series_graficos(inicio.isoformat(), fim.isoformat())["por_veiculo"]
    parados = []
    for v in Veiculo.query.filter_by(ativo=True).all():
        ordens = OrdemServico.query.filter(OrdemServico.veiculo_id == v.id,
                                           OrdemServico.data_abertura.between(inicio, fim)).all()
        parados.append({"veiculo": v.prefixo, "placa": v.placa,
                        "dias_parado": sum(o.dias_parado for o in ordens),
                        "ordens": len(ordens)})

    return {
        "melhor_consumo": sorted([m for m in lista_mot if m["consumo"]],
                                 key=lambda x: x["consumo"], reverse=True)[:10],
        "menor_custo_km": sorted([m for m in lista_mot if m["custo_km"]],
                                 key=lambda x: x["custo_km"])[:10],
        "veiculos_economicos": sorted([v for v in dados if v["consumo"]],
                                      key=lambda x: x["consumo"], reverse=True)[:10],
        "veiculos_caros": sorted(dados, key=lambda x: x["total"], reverse=True)[:10],
        "maior_tempo_parado": sorted(parados, key=lambda x: x["dias_parado"], reverse=True)[:10],
    }


def alertas():
    """Avisos automáticos — o coração preventivo do sistema."""
    cfg = current_app.config
    hoje = data_de_hoje()
    saida = []

    def add(nivel, categoria, titulo, detalhe, referencia=None):
        saida.append({"nivel": nivel, "categoria": categoria, "titulo": titulo,
                      "detalhe": detalhe, "referencia": referencia})

    for v in Veiculo.query.filter_by(ativo=True).all():
        # troca de óleo
        if v.intervalo_troca_oleo:
            faltam = v.km_proxima_troca_oleo - (v.hodometro or 0)
            if faltam <= 0:
                add("critico", "Óleo", f"{v.prefixo} · troca de óleo vencida",
                    f"{abs(faltam):,.0f} km além do intervalo previsto.".replace(",", "."), v.placa)
            elif faltam <= cfg["KM_AVISO_TROCA_OLEO"]:
                add("atencao", "Óleo", f"{v.prefixo} · troca de óleo próxima",
                    f"Faltam {faltam:,.0f} km.".replace(",", "."), v.placa)
        # preventiva atrasada
        if v.data_ultima_preventiva and v.intervalo_preventiva_dias:
            venc = v.data_ultima_preventiva + timedelta(days=v.intervalo_preventiva_dias)
            if venc < hoje:
                add("critico", "Preventiva", f"{v.prefixo} · preventiva atrasada",
                    f"Vencida em {venc.strftime('%d/%m/%Y')} ({(hoje - venc).days} dias).", v.placa)
            elif (venc - hoje).days <= 7:
                add("atencao", "Preventiva", f"{v.prefixo} · preventiva a vencer",
                    f"Programada para {venc.strftime('%d/%m/%Y')}.", v.placa)
        # orçamento do mês
        if v.orcamento_mensal:
            ini = hoje.replace(day=1)
            ordens = OrdemServico.query.filter(OrdemServico.veiculo_id == v.id,
                                               OrdemServico.data_abertura.between(ini, hoje)).all()
            comb = db.session.query(func.sum(Abastecimento.valor_total)).filter(
                Abastecimento.veiculo_id == v.id,
                Abastecimento.data.between(ini, hoje)).scalar() or 0
            gasto = sum(o.custo_total for o in ordens) + comb
            if gasto > v.orcamento_mensal:
                add("critico", "Orçamento", f"{v.prefixo} · acima do orçamento",
                    f"R$ {gasto:,.2f} gastos contra R$ {v.orcamento_mensal:,.2f} previstos."
                    .replace(",", "X").replace(".", ",").replace("X", "."), v.placa)

        # consumo pior que a média histórica
        media_hist = db.session.query(func.avg(Abastecimento.km_por_litro)).filter(
            Abastecimento.veiculo_id == v.id, Abastecimento.km_por_litro > 0).scalar()
        ultimos = (Abastecimento.query.filter(Abastecimento.veiculo_id == v.id,
                                              Abastecimento.km_por_litro > 0)
                   .order_by(Abastecimento.data.desc()).limit(3).all())
        if media_hist and len(ultimos) >= 3:
            media_recente = sum(a.km_por_litro for a in ultimos) / len(ultimos)
            if media_recente < media_hist * (1 - cfg["DESVIO_CONSUMO_ALERTA"]):
                add("atencao", "Consumo", f"{v.prefixo} · consumo acima do normal",
                    f"Média recente {media_recente:.2f} km/L contra {media_hist:.2f} km/L histórica.",
                    v.placa)

    # pneus no limite
    for p in Pneu.query.filter(Pneu.status == "Em uso").all():
        if (p.sulco_mm or 0) < cfg["SULCO_MINIMO_MM"]:
            add("critico", "Pneus", f"Pneu {p.numero_fogo} abaixo do sulco mínimo",
                f"{p.sulco_mm:.1f} mm em {p.posicao or 'posição não informada'} "
                f"({p.veiculo.prefixo if p.veiculo else 'sem veículo'}). Limite: "
                f"{cfg['SULCO_MINIMO_MM']:.0f} mm.", p.numero_fogo)
        elif (p.sulco_mm or 0) < cfg["SULCO_MINIMO_MM"] + 1:
            add("atencao", "Pneus", f"Pneu {p.numero_fogo} próximo do limite",
                f"{p.sulco_mm:.1f} mm — programe a troca.", p.numero_fogo)

    # estoque abaixo do mínimo
    for pe in Peca.query.filter(Peca.quantidade <= Peca.estoque_minimo).all():
        add("atencao", "Estoque", f"{pe.codigo} abaixo do estoque mínimo",
            f"Saldo {pe.quantidade:g} {pe.unidade} · mínimo {pe.estoque_minimo:g}.", pe.codigo)

    # falhas recorrentes no mesmo componente
    limite = hoje - timedelta(days=90)
    recorrentes = (db.session.query(OrdemServico.veiculo_id, OrdemServico.grupo,
                                    func.count(OrdemServico.id))
                   .filter(OrdemServico.data_abertura >= limite,
                           OrdemServico.tipo.in_(["Corretiva", "Emergencial"]))
                   .group_by(OrdemServico.veiculo_id, OrdemServico.grupo)
                   .having(func.count(OrdemServico.id) >= 3).all())
    for veiculo_id, grupo, qtd in recorrentes:
        v = db.session.get(Veiculo, veiculo_id)
        add("critico", "Recorrência", f"{v.prefixo if v else '—'} · falhas repetidas em {grupo or 'componente'}",
            f"{qtd} corretivas nos últimos 90 dias. Avalie causa raiz.", v.placa if v else None)

    ordem = {"critico": 0, "atencao": 1, "info": 2}
    saida.sort(key=lambda a: ordem.get(a["nivel"], 3))
    return saida
