"""Diagnóstico NF x abastecimentos de combustível. SOMENTE CONSULTA (SELECT).

Como rodar (Shell do Render, na pasta do projeto):

    python diagnostico_combustivel.py

Nada é gravado: o cálculo roda em modo consulta (persistir=False, sem autoflush)
e a sessão é desfeita (rollback) no final.

Responde:
  1. Qual é a data de início do controle e quais NFs existem (por mês).
  2. Quantos abastecimentos existem por mês, litros, valor e quantos estão
     com valor R$ 0 (sem valorização).
  3. Litros por dia de setembro no sistema x planilha (TOTAIS).
  4. Kardex: litros comprados, consumidos, saldo, custo médio e alertas.
  5. Inconsistências: NF com total != litros x valor/litro, abastecimentos
     duplicados, abastecimentos antes do início do controle.
"""
import os
from collections import defaultdict

os.environ["AGENDADOR_ATIVO"] = "0"
os.environ["ALERTAS_EMAIL_ATIVO"] = "0"

from datetime import date

from sqlalchemy import func

from app import app
from extensions import db
from models import (Abastecimento, AjusteEstoqueCombustivel,
                    ControleEstoqueCombustivel, NotaFiscalCombustivel)

# Litros por dia na planilha 09 - ABASTECIMENTO SETEMBRO 2026 (aba TOTAIS).
PLANILHA_SETEMBRO = {
    1: 5480, 2: 7351, 3: 4470, 4: 7509, 5: 5002, 7: 7029, 8: 5760, 9: 6099,
    10: 6339, 11: 5912, 12: 5894, 14: 6509, 15: 7331, 16: 5485, 17: 6135,
    18: 5369, 19: 6308, 21: 5981, 22: 6843, 23: 6139, 24: 5947, 25: 6013,
}


def num(v, casas=2):
    s = f"{(v or 0):,.{casas}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def titulo(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)


def main():
    with app.app_context(), db.session.no_autoflush:
        try:
            # ------------------------------------------------------ 1. controle e NFs
            titulo("1. CONTROLE DE ESTOQUE E NOTAS FISCAIS")
            controles = ControleEstoqueCombustivel.query.all()
            for c in controles:
                print(f"  Controle {c.combustivel}: início em {c.data_inicio}")
            if not controles:
                print("  Nenhum controle ativo (sem NF lançada).")

            nfs = (NotaFiscalCombustivel.query
                   .order_by(NotaFiscalCombustivel.data_entrada, NotaFiscalCombustivel.id).all())
            print(f"  Total de NFs: {len(nfs)}")
            por_mes = defaultdict(lambda: [0, 0.0, 0.0])
            for n in nfs:
                d = n.data_entrada or n.data
                k = (n.combustivel, d.strftime("%Y-%m"))
                por_mes[k][0] += 1
                por_mes[k][1] += n.litros or 0
                por_mes[k][2] += n.valor_total or 0
            for (comb, mes), (q, l, v) in sorted(por_mes.items()):
                print(f"  {mes} {comb}: {q} NF(s), {num(l)} L, R$ {num(v)}")
            print("\n  Lista de NFs:")
            for n in nfs:
                d = n.data_entrada or n.data
                print(f"   NF {n.numero_nf:>10} | entrada {d} | fiscal {n.data} | "
                      f"{num(n.litros)} L x R$ {num(n.valor_litro, 4)} = R$ {num(n.valor_total)}")

            # ------------------------------------------- 2. abastecimentos por mês
            titulo("2. ABASTECIMENTOS POR MÊS")
            linhas = (db.session.query(
                func.to_char(Abastecimento.data, "YYYY-MM"), Abastecimento.combustivel,
                func.count(Abastecimento.id), func.coalesce(func.sum(Abastecimento.litros), 0),
                func.coalesce(func.sum(Abastecimento.valor_total), 0),
                func.sum(db.case((func.coalesce(Abastecimento.valor_litro, 0) == 0, 1), else_=0)))
                .group_by(func.to_char(Abastecimento.data, "YYYY-MM"), Abastecimento.combustivel)
                .order_by(func.to_char(Abastecimento.data, "YYYY-MM")).all())
            for mes, comb, q, l, v, zero in linhas:
                print(f"  {mes} {comb}: {q} lançamentos, {num(l)} L, R$ {num(v)}, "
                      f"sem valor (R$/L = 0): {zero or 0}")

            # --------------------------------- 3. setembro: sistema x planilha
            titulo("3. SETEMBRO/2026: LITROS POR DIA, SISTEMA x PLANILHA")
            dia_sis = defaultdict(float)
            for a in Abastecimento.query.filter(Abastecimento.data >= date(2026, 9, 1),
                                                Abastecimento.data <= date(2026, 9, 30)).all():
                dia_sis[a.data.day] += a.litros or 0
            tot_s = tot_p = 0.0
            print("  dia | sistema |  planilha | diferença")
            for d in sorted(set(dia_sis) | set(PLANILHA_SETEMBRO)):
                s, p = dia_sis.get(d, 0.0), PLANILHA_SETEMBRO.get(d, 0)
                tot_s += s
                tot_p += p
                marca = "" if abs(s - p) < 0.5 else "  <-- difere"
                print(f"  {d:02d}  | {num(s, 0):>8} | {num(p, 0):>9} | {num(s - p, 0):>8}{marca}")
            print(f"  TOTAL: sistema {num(tot_s, 0)} L | planilha {num(tot_p, 0)} L | "
                  f"diferença {num(tot_s - tot_p, 0)} L")

            # ------------------------------------------------------ 4. kardex
            titulo("4. KARDEX (cálculo do sistema, sem gravar)")
            from services.estoque_combustivel import recalcular_estoque_combustivel
            for c in controles:
                r = recalcular_estoque_combustivel(
                    c.combustivel, validar=False, estrito=False, persistir=False)
                print(f"  {r['combustivel']} desde {r['data_inicio']}")
                print(f"    Comprado : {num(r['litros_comprados'])} L | R$ {num(r['valor_comprado'])}")
                print(f"    Consumido: {num(r['litros_consumidos'])} L | R$ {num(r['valor_consumido'])}")
                print(f"    Saldo    : {num(r['litros_estoque'])} L | R$ {num(r['valor_estoque'])} "
                      f"| custo médio R$ {num(r['custo_medio'], 4)}")
                conta = r["litros_comprados"] - r["litros_consumidos"]
                print(f"    Conferência: comprado - consumido = {num(conta)} L "
                      f"(difere do saldo por ajustes/falta de estoque: "
                      f"{num(r['litros_estoque'] - conta)} L)")
                print(f"    Alertas: {len(r['alertas'])}")
                for a in r["alertas"][:15]:
                    print(f"      - {a}")
                if len(r["alertas"]) > 15:
                    print(f"      ... e mais {len(r['alertas']) - 15}")

                antes = (Abastecimento.query
                         .filter(Abastecimento.combustivel == c.combustivel,
                                 Abastecimento.data < c.data_inicio).all())
                print(f"    Abastecimentos ANTES do início do controle (fora do kardex): "
                      f"{len(antes)} lançamentos, {num(sum(a.litros or 0 for a in antes))} L")

            ajustes = AjusteEstoqueCombustivel.query.order_by(AjusteEstoqueCombustivel.data).all()
            print(f"\n  Ajustes de estoque: {len(ajustes)}")
            for aj in ajustes:
                print(f"    {aj.data} {aj.combustivel}: saldo físico {aj.saldo_fisico} "
                      f"| delta {aj.litros} | {aj.motivo}")

            # ------------------------------------------------ 5. inconsistências
            titulo("5. INCONSISTÊNCIAS")
            ruins = [n for n in nfs
                     if abs((n.litros or 0) * (n.valor_litro or 0) - (n.valor_total or 0)) > 1.0]
            print(f"  NFs com total != litros x valor/litro (tolerância R$ 1,00): {len(ruins)}")
            for n in ruins:
                print(f"    NF {n.numero_nf}: {num(n.litros)} x {num(n.valor_litro, 4)} = "
                      f"{num((n.litros or 0) * (n.valor_litro or 0))} | gravado {num(n.valor_total)}")

            vistos = defaultdict(list)
            for a in Abastecimento.query.all():
                vistos[(a.veiculo_id, a.data, a.litros, a.km_atual)].append(a.id)
            dup = {k: v for k, v in vistos.items() if len(v) > 1}
            print(f"  Abastecimentos duplicados (mesmo veículo/data/litros/km): {len(dup)}")
            for k, ids in list(dup.items())[:15]:
                print(f"    veículo {k[0]} {k[1]} {num(k[2], 0)} L km {num(k[3], 0)} -> ids {ids}")

            sem_valor = Abastecimento.query.filter(
                func.coalesce(Abastecimento.valor_litro, 0) == 0).count()
            print(f"  Abastecimentos com R$/L = 0 (nunca valorizados): {sem_valor}")
            print("\nFim. Nada foi gravado.")
        finally:
            db.session.rollback()


if __name__ == "__main__":
    main()
