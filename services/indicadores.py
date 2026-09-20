"""KPIs do painel executivo, rankings e alertas automáticos."""
import calendar
from datetime import date, timedelta

from flask import current_app
from sqlalchemy import case, func

from extensions import db
from models import (Abastecimento, ItemOS, Lavagem, MovimentoEstoque, NotaFiscal, OrdemServico,
                    Orcamento, Peca, Pneu, ServicoTerceiro, Veiculo)
from services.auditoria_estoque import contar_os_pendentes
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
    """Custo da frota, excluindo setores antigos que eram veículos artificiais."""
    q = (OrdemServico.query
         .join(Veiculo, OrdemServico.veiculo_id == Veiculo.id)
         .filter(OrdemServico.data_abertura.between(inicio, fim),
                 Veiculo.grupo_consumo_legado.isnot(True)))
    if veiculo_id:
        q = q.filter(OrdemServico.veiculo_id == veiculo_id)
    return q.all()


def _servicos_terceiros(inicio, fim, veiculo_id=None):
    """Despesas externas contadas pela data real do lançamento."""
    q = ServicoTerceiro.query.filter(ServicoTerceiro.data.between(inicio, fim))
    if veiculo_id:
        q = q.filter(ServicoTerceiro.veiculo_id == veiculo_id)
    return q.all()


def _lavagens(inicio, fim, veiculo_id=None):
    """Despesas de lavagem contadas pela data real do lançamento."""
    q = Lavagem.query.filter(Lavagem.data.between(inicio, fim))
    if veiculo_id:
        q = q.filter(Lavagem.veiculo_id == veiculo_id)
    return q.all()


def _notas_finalizadas(inicio, fim):
    """Notas fiscais de entrada (Módulo 11) finalizadas no período — o gasto
    real de compra de peças, contado pela data em que a nota deu entrada no
    estoque (data_entrada), não pela data de emissão. Nota 'Aberta' ainda não
    virou entrada de fato, então não conta como gasto."""
    return NotaFiscal.query.filter(
        NotaFiscal.status == "Finalizada",
        NotaFiscal.data_entrada.between(inicio, fim)).all()


def _custo_km_historico(ate, veiculo_id=None):
    """Custo por km da frota antes do período — a régua da comparação."""
    q_ab = Abastecimento.query.filter(Abastecimento.data < ate)
    q_os = (OrdemServico.query.join(Veiculo, OrdemServico.veiculo_id == Veiculo.id)
            .filter(OrdemServico.data_abertura < ate,
                    Veiculo.grupo_consumo_legado.isnot(True)))
    q_terc = ServicoTerceiro.query.filter(ServicoTerceiro.data < ate)
    if veiculo_id:
        q_ab = q_ab.filter(Abastecimento.veiculo_id == veiculo_id)
        q_os = q_os.filter(OrdemServico.veiculo_id == veiculo_id)
        q_terc = q_terc.filter(ServicoTerceiro.veiculo_id == veiculo_id)

    abastecimentos = q_ab.all()
    km = sum(a.km_percorridos or 0 for a in abastecimentos)
    if km < 500:            # histórico curto demais para servir de referência
        return None
    gasto = (sum(a.valor_total or 0 for a in abastecimentos)
             + sum(o.custo_total for o in q_os.all())
             + sum(s.valor or 0 for s in q_terc.all()))
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
    servicos_terceiros = _servicos_terceiros(inicio, fim, veiculo_id)
    lavagens = _lavagens(inicio, fim, veiculo_id)

    q_ab = Abastecimento.query.filter(Abastecimento.data.between(inicio, fim))
    if veiculo_id:
        q_ab = q_ab.filter(Abastecimento.veiculo_id == veiculo_id)
    abastecimentos = q_ab.all()

    veiculos = Veiculo.query.filter(Veiculo.ativo.is_(True),
                                    Veiculo.grupo_consumo_legado.isnot(True))
    if veiculo_id:
        veiculos = veiculos.filter(Veiculo.id == veiculo_id)
    veiculos = veiculos.all()
    total_veic = len(veiculos) or 1

    gasto_manut_os = round(sum(o.custo_total for o in ordens), 2)
    gasto_terceiros = round(sum(s.valor or 0 for s in servicos_terceiros), 2)
    gasto_manut = round(gasto_manut_os + gasto_terceiros, 2)
    gasto_lavagem = round(sum(l.valor or 0 for l in lavagens), 2)
    gasto_comb = round(sum(a.valor_total or 0 for a in abastecimentos), 2)
    notas_compra = _notas_finalizadas(inicio, fim)
    gasto_compras = round(sum(n.valor_total for n in notas_compra), 2)
    litros = sum(a.litros or 0 for a in abastecimentos)
    km_rodados = sum(a.km_percorridos or 0 for a in abastecimentos)
    # "média da média" da frota: média simples do km/L de cada abastecimento
    # do período (em vez de soma_km / soma_litros) — fica ao lado de
    # "consumo_medio" (soma/soma) só para comparação.
    kml_validos = [a.km_por_litro for a in abastecimentos if a.km_por_litro]
    consumo_medio_media_da_media = round(sum(kml_validos) / len(kml_validos), 2) if kml_validos else 0

    finalizadas = [o for o in ordens if o.status == "Finalizada" and o.data_fechamento]
    corretivas = [o for o in ordens if o.tipo in ("Corretiva", "Emergencial")]
    dias_periodo = max((fim - inicio).days + 1, 1)
    horas_paradas = sum(o.dias_parado * 24 for o in ordens)
    horas_disponiveis = total_veic * dias_periodo * 24

    mttr = round(sum(o.dias_parado for o in finalizadas) / len(finalizadas), 1) if finalizadas else 0
    mtbf = round((total_veic * dias_periodo) / len(corretivas), 1) if corretivas else 0

    orcado = db.session.query(func.sum(Orcamento.meta_valor)).filter(
        Orcamento.ano == fim.year, Orcamento.mes == fim.month,
        Orcamento.grupo_consumo_id.is_(None),
        ~Orcamento.veiculo.has(Veiculo.grupo_consumo_legado.is_(True))).scalar() or 0

    # Economia do período: quanto o custo por km atual está melhor (ou pior)
    # que a média histórica, aplicado aos km rodados agora.
    custo_km_atual = round((gasto_comb + gasto_manut + gasto_lavagem) / km_rodados, 4) if km_rodados else 0
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
        "gasto_manutencao_os": gasto_manut_os,
        "gasto_servicos_terceiros": gasto_terceiros,
        "servicos_terceiros_qtd": len(servicos_terceiros),
        "gasto_manutencao": gasto_manut,
        "gasto_lavagem": gasto_lavagem,
        "lavagens_qtd": len(lavagens),
        "gasto_total": round(gasto_comb + gasto_manut + gasto_lavagem, 2),
        "gasto_compras": gasto_compras,
        "notas_fiscais_qtd": len(notas_compra),
        # Gasto total "geral" soma compras de peças (Módulo 11) ao gasto da
        # frota. Fica em campo à parte para não mudar o que "Gasto total" e a
        # aderência ao orçamento por veículo sempre significaram no painel.
        "gasto_total_geral": round(gasto_comb + gasto_manut + gasto_lavagem + gasto_compras, 2),
        "km_rodados": round(km_rodados),
        "consumo_medio": round(km_rodados / litros, 2) if litros else 0,
        "consumo_medio_media_da_media": consumo_medio_media_da_media,
        "custo_por_km": round((gasto_comb + gasto_manut + gasto_lavagem) / km_rodados, 2) if km_rodados else 0,
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
        "os_estoque_pendentes": contar_os_pendentes(),
        "os_preventivas": sum(1 for o in ordens if o.tipo == "Preventiva"),
        "os_corretivas": len(corretivas),
        "orcamento_mes": round(orcado, 2),
        "aderencia_orcamento": round((gasto_comb + gasto_manut + gasto_lavagem) / orcado * 100, 1) if orcado else 0,
        "estoque_valor": round(sum((p.quantidade or 0) * (p.custo_unitario or 0)
                                   for p in Peca.query.all()), 2),
        "estoque_critico": Peca.query.filter(Peca.estoque_minimo > 0,
                                             Peca.quantidade <= Peca.estoque_minimo).count(),
    }


def horas_por_mecanico(inicio=None, fim=None):
    """Horas trabalhadas por mecânico no período, a partir das OS com
    início e fim registrados (usa OrdemServico.duracao_minutos, que já
    prioriza hora_inicio_servico sobre hora_inicio quando disponível).

    Nomes são normalizados (mesma lógica de /mecanicos-os) para que
    "cleiton", "CLEITON" e "Cleiton" sejam somados como um único mecânico.
    """
    inicio, fim = periodo_padrao(inicio, fim)

    ordens = (OrdemServico.query
              .filter(OrdemServico.data_abertura.between(inicio, fim),
                      OrdemServico.mecanico.isnot(None),
                      OrdemServico.mecanico != "")
              .all())

    agregados = {}
    for o in ordens:
        chave = o.mecanico.strip().upper()
        registro = agregados.setdefault(chave, {
            "mecanico": o.mecanico.strip().title(), "os": 0, "minutos": 0, "custo": 0.0,
        })
        registro["os"] += 1
        registro["minutos"] += o.duracao_minutos or 0
        registro["custo"] += o.custo_total or 0

    linhas = [{
        "mecanico": v["mecanico"],
        "os": v["os"],
        "horas": round(v["minutos"] / 60, 2),
        "horas_str": f"{v['minutos'] // 60}h{v['minutos'] % 60:02d}m",
        "custo": round(v["custo"], 2),
    } for v in agregados.values()]
    linhas.sort(key=lambda x: x["horas"], reverse=True)

    return linhas


def series_graficos(inicio=None, fim=None):
    """Dados dos gráficos do dashboard (módulos 6, 8 e 9)."""
    inicio, fim = periodo_padrao(inicio, fim)
    hoje = data_de_hoje()

    # 12 meses móveis de gasto
    meses, comb_mes, manut_mes, compras_mes, meta_mes, lavagem_mes = [], [], [], [], [], []
    for i in range(11, -1, -1):
        ref = (hoje.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        ini = ref
        f = ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
        meses.append(f"{MESES[ref.month - 1]}/{str(ref.year)[2:]}")
        comb_mes.append(round(db.session.query(func.sum(Abastecimento.valor_total))
                              .filter(Abastecimento.data.between(ini, f)).scalar() or 0, 2))
        ordens = _custo_os(ini, f)
        terceiros = _servicos_terceiros(ini, f)
        manut_mes.append(round(sum(o.custo_total for o in ordens)
                               + sum(s.valor or 0 for s in terceiros), 2))
        lavagem_mes.append(round(sum(l.valor or 0 for l in _lavagens(ini, f)), 2))
        compras_mes.append(round(sum(n.valor_total for n in _notas_finalizadas(ini, f)), 2))
        meta_mes.append(round(db.session.query(func.sum(Orcamento.meta_valor))
                              .filter(Orcamento.ano == ref.year, Orcamento.mes == ref.month,
                                      Orcamento.grupo_consumo_id.is_(None),
                                      ~Orcamento.veiculo.has(Veiculo.grupo_consumo_legado.is_(True)))
                              .scalar() or 0, 2))

    # custo por veículo no período
    por_veiculo = []
    for v in Veiculo.query.filter(Veiculo.ativo.is_(True),
                                  Veiculo.grupo_consumo_legado.isnot(True)).all():
        ordens = OrdemServico.query.filter(OrdemServico.veiculo_id == v.id,
                                           OrdemServico.data_abertura.between(inicio, fim)).all()
        terceiros = _servicos_terceiros(inicio, fim, v.id)
        lavagens_v = _lavagens(inicio, fim, v.id)
        comb = db.session.query(func.sum(Abastecimento.valor_total)).filter(
            Abastecimento.veiculo_id == v.id,
            Abastecimento.data.between(inicio, fim)).scalar() or 0
        km = db.session.query(func.sum(Abastecimento.km_percorridos)).filter(
            Abastecimento.veiculo_id == v.id,
            Abastecimento.data.between(inicio, fim)).scalar() or 0
        litros = db.session.query(func.sum(Abastecimento.litros)).filter(
            Abastecimento.veiculo_id == v.id,
            Abastecimento.data.between(inicio, fim)).scalar() or 0
        # "média da média": média simples do km/L de cada abastecimento do
        # veículo no período (em vez de soma_km / soma_litros). Cada
        # abastecimento pesa igual, independente do volume abastecido -
        # fica ao lado de "consumo" (soma/soma) só para comparação.
        consumo_media_da_media = round(
            db.session.query(func.avg(Abastecimento.km_por_litro)).filter(
                Abastecimento.veiculo_id == v.id,
                Abastecimento.data.between(inicio, fim),
                Abastecimento.km_por_litro > 0).scalar() or 0, 2)
        gasto_terceiros = round(sum(s.valor or 0 for s in terceiros), 2)
        gasto_lavagem_v = round(sum(l.valor or 0 for l in lavagens_v), 2)
        manutencao = round(sum(o.custo_total for o in ordens) + gasto_terceiros, 2)
        total = round(manutencao + comb + gasto_lavagem_v, 2)
        por_veiculo.append({
            "veiculo": v.prefixo, "placa": v.placa, "manutencao": manutencao,
            "servicos_terceiros": gasto_terceiros, "lavagem": gasto_lavagem_v,
            "combustivel": round(comb, 2), "total": total, "km": round(km),
            "consumo": round(km / litros, 2) if litros else 0,
            "consumo_media_da_media": consumo_media_da_media,
            "custo_km": round(total / km, 2) if km else 0,
            "orcamento": v.orcamento_mensal or 0,
        })
    por_veiculo.sort(key=lambda x: x["total"], reverse=True)

    # custo por grupo de peças + consumo por produto (alimenta o Top 15)
    grupos = {}
    consumo = {}

    def _somar_consumo(chave, rotulo, qtd, valor):
        registro = consumo.setdefault(chave, {"peca": rotulo, "quantidade": 0.0,
                                              "valor": 0.0})
        registro["quantidade"] += qtd
        registro["valor"] += valor

    for item in (db.session.query(ItemOS).join(OrdemServico).join(Veiculo)
                 .filter(OrdemServico.data_abertura.between(inicio, fim),
                         Veiculo.grupo_consumo_legado.isnot(True)).all()):
        chave = item.grupo or (item.peca.grupo if item.peca else None) or "Outros"
        grupos[chave] = round(grupos.get(chave, 0) + (item.quantidade or 0) * (item.valor_unitario or 0), 2)

        qtd = item.quantidade or 0
        valor = qtd * (item.valor_unitario or 0)
        if item.peca:
            _somar_consumo(f"p{item.peca.id}",
                           f"{item.peca.codigo} · {item.peca.descricao}", qtd, valor)
        elif (item.descricao or "").strip():
            texto = item.descricao.strip()
            _somar_consumo("d" + texto.casefold(), texto, qtd, valor)

    # Saídas de estoque sem OS (ex.: óleo entregue direto no balcão) também
    # contam como uso da frota. As saídas ligadas a uma OS já entraram acima,
    # pelos itens da própria OS — ficam de fora aqui para não contar em dobro.
    for mov in (MovimentoEstoque.query
                .filter(MovimentoEstoque.tipo == "saida",
                        MovimentoEstoque.ordem_servico_id.is_(None),
                        MovimentoEstoque.grupo_consumo_id.is_(None),
                        MovimentoEstoque.data.between(inicio, fim)).all()):
        if not mov.peca:
            continue
        qtd = mov.quantidade or 0
        _somar_consumo(f"p{mov.peca.id}", f"{mov.peca.codigo} · {mov.peca.descricao}",
                       qtd, qtd * (mov.custo_unitario or 0))

    # Uniformes nunca entram: vivem em tabelas próprias (itens_uniforme /
    # movimentos_uniforme), separadas do estoque de peças.
    top_pecas = sorted(consumo.values(), key=lambda p: p["quantidade"], reverse=True)[:15]
    for p in top_pecas:
        p["quantidade"] = round(p["quantidade"], 2)
        p["valor"] = round(p["valor"], 2)
        if len(p["peca"]) > 58:      # etiqueta curta para caber no gráfico
            p["peca"] = p["peca"][:57] + "…"

    ordens_periodo = _custo_os(inicio, fim)
    tipos = {"Preventiva": 0, "Corretiva": 0, "Emergencial": 0}
    for o in ordens_periodo:
        tipos[o.tipo] = tipos.get(o.tipo, 0) + 1

    return {
        "meses": meses, "combustivel_mes": comb_mes, "manutencao_mes": manut_mes,
        "compras_mes": compras_mes, "lavagem_mes": lavagem_mes,
        "meta_mes": meta_mes,
        "realizado_mes": [round(c + m + l, 2) for c, m, l in zip(comb_mes, manut_mes, lavagem_mes)],
        "realizado_geral_mes": [round(c + m + l + p, 2)
                                for c, m, l, p in zip(comb_mes, manut_mes, lavagem_mes, compras_mes)],
        "por_veiculo": por_veiculo[:10],
        "grupos": {"labels": list(grupos.keys()), "valores": list(grupos.values())},
        "tipos_manutencao": tipos,
        "top_pecas": top_pecas,
        "consumo_veiculo": sorted(
            [{"veiculo": v["veiculo"], "consumo": v["consumo"],
              "consumo_media_da_media": v["consumo_media_da_media"]}
             for v in por_veiculo if v["consumo"]],
            key=lambda x: x["consumo"], reverse=True)[:10],
    }


def combustivel_por_dia(inicio=None, fim=None):
    """Litros e km/L de cada dia do período — alimenta o gráfico "Litros
    abastecidos por dia" do painel (mesma ideia da aba TOTAIS da planilha).

    O km/L do dia só usa os abastecimentos que têm km rodados calculado (o
    primeiro lançamento de um veículo não tem anterior para comparar), para
    não puxar a média para baixo.
    """
    inicio, fim = periodo_padrao(inicio, fim)
    com_km = Abastecimento.km_percorridos > 0
    linhas = (db.session.query(
                  Abastecimento.data,
                  func.sum(Abastecimento.litros),
                  func.sum(case((com_km, Abastecimento.litros), else_=0)),
                  func.sum(Abastecimento.km_percorridos),
                  func.count(Abastecimento.id),
                  func.count(func.distinct(Abastecimento.veiculo_id)))
              .filter(Abastecimento.data.between(inicio, fim))
              .group_by(Abastecimento.data)
              .order_by(Abastecimento.data)
              .all())

    dias, total_litros, total_litros_km, total_km = [], 0.0, 0.0, 0.0
    for data, litros, litros_com_km, km, qtd, veiculos in linhas:
        litros, litros_com_km, km = litros or 0, litros_com_km or 0, km or 0
        total_litros += litros
        total_litros_km += litros_com_km
        total_km += km
        dias.append({
            "data": data.isoformat(), "litros": round(litros, 1), "km": round(km),
            "km_por_litro": round(km / litros_com_km, 2) if litros_com_km else 0,
            "abastecimentos": qtd, "veiculos": veiculos,
        })
    return {
        "dias": dias,
        "total_litros": round(total_litros, 1),
        "media_litros_dia": round(total_litros / len(dias), 1) if dias else 0,
        "km_por_litro": round(total_km / total_litros_km, 2) if total_litros_km else 0,
    }


def _ordem_frota(prefixo):
    """Ordena 01, 02, ... 10 pelo número; prefixos com letras vão depois."""
    texto = str(prefixo or "").strip()
    return (0, int(texto), texto) if texto.isdigit() else (1, 0, texto.upper())


def consumo_frotas(inicio=None, fim=None):
    """Km/L de TODAS as frotas ativas no período e no período anterior.

    O período anterior tem o mesmo número de dias e termina no dia anterior
    ao início do filtro (ex.: 01/09–20/09 é comparado com 12/08–31/08). O
    km/L é soma dos km rodados ÷ soma dos litros do período — a mesma conta
    do gráfico "Consumo por veículo" do painel. Frotas sem abastecimento
    aparecem mesmo assim (consumo 0), para o relatório listar a frota toda.
    """
    inicio, fim = periodo_padrao(inicio, fim)
    dias = (fim - inicio).days + 1
    fim_ant = inicio - timedelta(days=1)
    inicio_ant = fim_ant - timedelta(days=dias - 1)

    def somas(ini, final):
        linhas = (db.session.query(Abastecimento.veiculo_id,
                                   func.sum(Abastecimento.litros),
                                   func.sum(Abastecimento.km_percorridos))
                  .filter(Abastecimento.data.between(ini, final))
                  .group_by(Abastecimento.veiculo_id).all())
        return {vid: (litros or 0, km or 0) for vid, litros, km in linhas}

    atual, anterior = somas(inicio, fim), somas(inicio_ant, fim_ant)

    def kml(litros, km):
        return round(km / litros, 2) if litros and km else 0

    def montar(rotulo_frota, placa, litros, km, litros_ant, km_ant):
        consumo, consumo_ant = kml(litros, km), kml(litros_ant, km_ant)
        variacao = variacao_pct = None
        if consumo and consumo_ant:
            variacao = round(consumo - consumo_ant, 2)
            variacao_pct = round((consumo - consumo_ant) / consumo_ant * 100, 1)
            evolucao = ("estavel" if abs(variacao_pct) < 1
                        else "melhorou" if variacao > 0 else "piorou")
        else:
            evolucao = "sem_dados" if not consumo else "sem_base"
        return {"veiculo": rotulo_frota, "placa": placa,
                "litros": round(litros, 1), "km": round(km),
                "consumo": consumo, "consumo_anterior": consumo_ant,
                "variacao": variacao, "variacao_pct": variacao_pct,
                "evolucao": evolucao}

    frotas = []
    soma = [0.0, 0.0, 0.0, 0.0]
    veiculos = Veiculo.query.filter(Veiculo.ativo.is_(True),
                                    Veiculo.grupo_consumo_legado.isnot(True)).all()
    for v in sorted(veiculos, key=lambda x: _ordem_frota(x.prefixo)):
        litros, km = atual.get(v.id, (0, 0))
        litros_ant, km_ant = anterior.get(v.id, (0, 0))
        soma[0] += litros; soma[1] += km; soma[2] += litros_ant; soma[3] += km_ant
        frotas.append(montar(v.prefixo, v.placa_exibicao, litros, km, litros_ant, km_ant))

    return {
        "periodo_atual": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
        "periodo_anterior": {"inicio": inicio_ant.isoformat(), "fim": fim_ant.isoformat()},
        "frotas": frotas,
        "total": montar("FROTA TOTAL", "", *soma),
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
            "litros": 0, "km": 0, "custo": 0, "abastecimentos": 0, "_kml": []})
        m["litros"] += a.litros or 0
        m["km"] += a.km_percorridos or 0
        m["custo"] += a.valor_total or 0
        m["abastecimentos"] += 1
        if a.km_por_litro:
            m["_kml"].append(a.km_por_litro)
    lista_mot = []
    for m in motoristas.values():
        kml_lista = m.pop("_kml")
        lista_mot.append({**m,
                          "consumo": round(m["km"] / m["litros"], 2) if m["litros"] else 0,
                          # "média da média": média simples do km/L de cada
                          # abastecimento do motorista no período.
                          "consumo_media_da_media": round(sum(kml_lista) / len(kml_lista), 2)
                          if kml_lista else 0,
                          "custo_km": round(m["custo"] / m["km"], 2) if m["km"] else 0,
                          "km": round(m["km"]), "litros": round(m["litros"], 1),
                          "custo": round(m["custo"], 2)})

    dados = series_graficos(inicio.isoformat(), fim.isoformat())["por_veiculo"]
    parados = []
    for v in Veiculo.query.filter(Veiculo.ativo.is_(True),
                                  Veiculo.grupo_consumo_legado.isnot(True)).all():
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

    def add(nivel, categoria, titulo, detalhe, referencia=None, veiculo=None):
        """veiculo: instância de Veiculo (ou None) ligada ao alerta, usada para
        expor a identificação da frota (prefixo/placa) de forma estruturada."""
        saida.append({"nivel": nivel, "categoria": categoria, "titulo": titulo,
                      "detalhe": detalhe, "referencia": referencia,
                      "frota": veiculo.prefixo if veiculo else None,
                      "placa": veiculo.placa if veiculo else None})

    for v in Veiculo.query.filter(Veiculo.ativo.is_(True),
                                  Veiculo.grupo_consumo_legado.isnot(True)).all():
        # troca de óleo
        if v.intervalo_troca_oleo:
            faltam = v.km_proxima_troca_oleo - (v.hodometro or 0)
            if faltam <= 0:
                add("critico", "Óleo", f"{v.prefixo} · troca de óleo vencida",
                    f"{abs(faltam):,.0f} km além do intervalo previsto.".replace(",", "."), v.placa,
                    veiculo=v)
            elif faltam <= cfg["KM_AVISO_TROCA_OLEO"]:
                add("atencao", "Óleo", f"{v.prefixo} · troca de óleo próxima",
                    f"Faltam {faltam:,.0f} km.".replace(",", "."), v.placa, veiculo=v)
        # preventiva atrasada
        if v.data_ultima_preventiva and v.intervalo_preventiva_dias:
            venc = v.data_ultima_preventiva + timedelta(days=v.intervalo_preventiva_dias)
            if venc < hoje:
                add("critico", "Preventiva", f"{v.prefixo} · preventiva atrasada",
                    f"Vencida em {venc.strftime('%d/%m/%Y')} ({(hoje - venc).days} dias).", v.placa,
                    veiculo=v)
            elif (venc - hoje).days <= 7:
                add("atencao", "Preventiva", f"{v.prefixo} · preventiva a vencer",
                    f"Programada para {venc.strftime('%d/%m/%Y')}.", v.placa, veiculo=v)
        # orçamento do mês
        if v.orcamento_mensal:
            ini = hoje.replace(day=1)
            ordens = OrdemServico.query.filter(OrdemServico.veiculo_id == v.id,
                                               OrdemServico.data_abertura.between(ini, hoje)).all()
            comb = db.session.query(func.sum(Abastecimento.valor_total)).filter(
                Abastecimento.veiculo_id == v.id,
                Abastecimento.data.between(ini, hoje)).scalar() or 0
            terceiros = _servicos_terceiros(ini, hoje, v.id)
            lavagens_v = _lavagens(ini, hoje, v.id)
            gasto = (sum(o.custo_total for o in ordens) + comb
                     + sum(s.valor or 0 for s in terceiros)
                     + sum(l.valor or 0 for l in lavagens_v))
            if gasto > v.orcamento_mensal:
                add("critico", "Orçamento", f"{v.prefixo} · acima do orçamento",
                    f"R$ {gasto:,.2f} gastos contra R$ {v.orcamento_mensal:,.2f} previstos."
                    .replace(",", "X").replace(".", ",").replace("X", "."), v.placa, veiculo=v)

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
                    v.placa, veiculo=v)

    # pneus no limite
    for p in Pneu.query.filter(Pneu.status == "Em uso").all():
        if (p.sulco_mm or 0) < cfg["SULCO_MINIMO_MM"]:
            add("critico", "Pneus", f"Pneu {p.numero_fogo} abaixo do sulco mínimo",
                f"{p.sulco_mm:.1f} mm em {p.posicao or 'posição não informada'} "
                f"({p.veiculo.prefixo if p.veiculo else 'sem veículo'}). Limite: "
                f"{cfg['SULCO_MINIMO_MM']:.0f} mm.", p.numero_fogo, veiculo=p.veiculo)
        elif (p.sulco_mm or 0) < cfg["SULCO_MINIMO_MM"] + 1:
            add("atencao", "Pneus", f"Pneu {p.numero_fogo} próximo do limite",
                f"{p.sulco_mm:.1f} mm — programe a troca.", p.numero_fogo, veiculo=p.veiculo)

    pendencias_estoque_os = contar_os_pendentes()
    if pendencias_estoque_os:
        add("atencao", "Estoque", "OS finalizadas com baixa pendente",
            f"{pendencias_estoque_os} OS precisam de conferência e regularização do estoque.",
            "auditoria_estoque_os")

    # estoque abaixo do mínimo
    for pe in Peca.query.filter(Peca.estoque_minimo > 0,
                                Peca.quantidade <= Peca.estoque_minimo).all():
        add("atencao", "Estoque", f"{pe.codigo} abaixo do estoque mínimo",
            f"Saldo {pe.quantidade:g} {pe.unidade} · mínimo {pe.estoque_minimo:g}.", pe.codigo)

    # falhas recorrentes no mesmo componente
    limite = hoje - timedelta(days=90)
    recorrentes = (db.session.query(OrdemServico.veiculo_id, OrdemServico.grupo,
                                    func.count(OrdemServico.id))
                   .join(Veiculo, OrdemServico.veiculo_id == Veiculo.id)
                   .filter(OrdemServico.data_abertura >= limite,
                           OrdemServico.tipo.in_(["Corretiva", "Emergencial"]),
                           Veiculo.grupo_consumo_legado.isnot(True))
                   .group_by(OrdemServico.veiculo_id, OrdemServico.grupo)
                   .having(func.count(OrdemServico.id) >= 3).all())
    for veiculo_id, grupo, qtd in recorrentes:
        v = db.session.get(Veiculo, veiculo_id)
        add("critico", "Recorrência", f"{v.prefixo if v else '—'} · falhas repetidas em {grupo or 'componente'}",
            f"{qtd} corretivas nos últimos 90 dias. Avalie causa raiz.", v.placa if v else None, veiculo=v)

    ordem = {"critico": 0, "atencao": 1, "info": 2}
    saida.sort(key=lambda a: ordem.get(a["nivel"], 3))
    return saida
