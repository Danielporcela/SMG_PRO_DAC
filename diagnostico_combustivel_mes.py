"""Diagnóstico do combustível por dia. SOMENTE CONSULTAS (SELECT), não grava nada.

Como rodar (Shell do Render, na pasta do projeto):

    python diagnostico_combustivel_mes.py            # mês atual
    python diagnostico_combustivel_mes.py 2026-10    # outro mês (AAAA-MM)

Mostra, para o mês:
  1. Por dia: nº de lançamentos, litros abastecidos, litros comprados (NFs
     pela data física de entrada) e ajustes físicos.
  2. Dias SEM nenhum abastecimento (possível atraso de lançamento).
  3. NFs do mês, com marcação das suspeitas (mesmo dia, litros e preço
     repetidos; total incoerente; números típicos de teste).
  4. Ajustes de estoque do mês (inclui os legados sem saldo físico).
"""
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

# Impede que ESTE processo ligue o agendador ou envie e-mails.
os.environ["AGENDADOR_ATIVO"] = "0"
os.environ["ALERTAS_EMAIL_ATIVO"] = "0"

from sqlalchemy import func  # noqa: E402

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Abastecimento, AjusteEstoqueCombustivel, NotaFiscalCombustivel  # noqa: E402


def br(v, casas=0):
    s = f"{v or 0:,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def titulo(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def limites_do_mes(arg):
    if arg:
        ano, mes = (int(x) for x in arg.split("-"))
    else:
        h = date.today()
        ano, mes = h.year, h.month
    ini = date(ano, mes, 1)
    prox = date(ano + (mes == 12), (mes % 12) + 1, 1)
    return ini, prox - timedelta(days=1)


def main(arg=None):
    ini, fim = limites_do_mes(arg)
    ate = min(fim, date.today())
    print(f"Período: {ini:%d/%m/%Y} a {fim:%d/%m/%Y} (conferindo até {ate:%d/%m/%Y})")

    # ------------------------------------------------------------ 1
    ab = {d: (n, l) for d, n, l in
          db.session.query(Abastecimento.data, func.count(Abastecimento.id),
                           func.sum(Abastecimento.litros))
          .filter(Abastecimento.data >= ini, Abastecimento.data <= fim)
          .group_by(Abastecimento.data).all()}

    nfs = (NotaFiscalCombustivel.query
           .filter(func.coalesce(NotaFiscalCombustivel.data_entrada, NotaFiscalCombustivel.data) >= ini,
                   func.coalesce(NotaFiscalCombustivel.data_entrada, NotaFiscalCombustivel.data) <= fim)
           .order_by(NotaFiscalCombustivel.data_entrada, NotaFiscalCombustivel.id).all())
    compra = defaultdict(float)
    for n in nfs:
        compra[n.data_entrada or n.data] += n.litros or 0

    ajustes = (AjusteEstoqueCombustivel.query
               .filter(AjusteEstoqueCombustivel.data >= ini, AjusteEstoqueCombustivel.data <= fim)
               .order_by(AjusteEstoqueCombustivel.data, AjusteEstoqueCombustivel.id).all())
    ajuste_dia = defaultdict(float)
    for a in ajustes:
        ajuste_dia[a.data] += a.litros or 0

    titulo("1) POR DIA")
    print(f"{'Dia':<12}{'Lanç.':>7}{'Abastecido L':>15}{'Comprado L':>14}{'Ajuste L':>14}")
    sem_lanc, tot_ab, tot_n, tot_c = [], 0.0, 0, 0.0
    d = ini
    while d <= fim:
        n, l = ab.get(d, (0, 0))
        l = l or 0
        marca = ""
        if d <= ate and n == 0:
            sem_lanc.append(d)
            marca = "  <-- sem abastecimento"
        if d <= ate or n or compra.get(d) or ajuste_dia.get(d):
            print(f"{d.strftime('%d/%m %a'):<12}{n:>7}{br(l):>15}{br(compra.get(d, 0)):>14}"
                  f"{br(ajuste_dia.get(d, 0), 2):>14}{marca}")
        tot_ab += l
        tot_n += n
        tot_c += compra.get(d, 0)
        d += timedelta(days=1)
    print("-" * 62)
    print(f"{'TOTAL':<12}{tot_n:>7}{br(tot_ab):>15}{br(tot_c):>14}")
    dias_com = len([x for x in ab if x <= ate])
    if dias_com:
        print(f"Média por dia com lançamento: {br(tot_ab / dias_com)} L "
              f"({dias_com} dia(s) com lançamento)")

    # ------------------------------------------------------------ 2
    titulo("2) DIAS SEM NENHUM ABASTECIMENTO")
    if not sem_lanc:
        print("Nenhum. Todos os dias até hoje têm lançamento.")
    else:
        print(", ".join(x.strftime("%d/%m") for x in sem_lanc))
        print("Domingos e feriados podem ser normais; o resto pode ser lançamento atrasado.")

    # ------------------------------------------------------------ 3
    titulo("3) NOTAS FISCAIS DO MÊS (data física de entrada)")
    grupos = defaultdict(list)
    for n in nfs:
        grupos[(n.data_entrada or n.data, round(n.litros or 0, 3), round(n.valor_litro or 0, 4))].append(n)
    print(f"{'Entrada':<8}{'NF':<14}{'Litros':>10}{'R$/L':>9}{'Total R$':>14}  Observação")
    for n in nfs:
        avisos = []
        chave = (n.data_entrada or n.data, round(n.litros or 0, 3), round(n.valor_litro or 0, 4))
        if len(grupos[chave]) > 1:
            avisos.append("MESMO DIA/LITROS/PREÇO de outra NF (duplicada?)")
        esperado = (n.litros or 0) * (n.valor_litro or 0)
        if abs(esperado - (n.valor_total or 0)) > 0.05:
            avisos.append(f"total != litros x R$/L (esperado {br(esperado, 2)})")
        if (n.valor_litro or 0) < 1:
            avisos.append("R$/L muito baixo")
        if (n.litros or 0) < 100 or "test" in (n.numero_nf or "").lower() \
                or (n.numero_nf or "").strip().lstrip("0") in ("1", ""):
            avisos.append("parece teste")
        if n.data_entrada and n.data and n.data_entrada != n.data:
            avisos.append(f"NF {n.data:%d/%m}")
        print(f"{(n.data_entrada or n.data):%d/%m}  {(n.numero_nf or '')[:13]:<14}{br(n.litros):>10}"
              f"{br(n.valor_litro, 3):>9}{br(n.valor_total, 2):>14}  {'; '.join(avisos)}")
    if not nfs:
        print("Nenhuma NF no período.")

    # ------------------------------------------------------------ 4
    titulo("4) AJUSTES DE ESTOQUE DO MÊS")
    if not ajustes:
        print("Nenhum.")
    for a in ajustes:
        fis = "SEM saldo físico (legado)" if a.saldo_fisico is None else f"saldo físico {br(a.saldo_fisico, 2)} L"
        print(f"id {a.id:<5}{a.data:%d/%m}  dif {br(a.litros, 2):>14} L  {fis:<30} "
              f"{(a.usuario or '-')[:14]:<14} {(a.motivo or '')[:50]}")


if __name__ == "__main__":
    with app.app_context():
        main(sys.argv[1] if len(sys.argv) > 1 else None)
