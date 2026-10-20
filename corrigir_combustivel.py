"""Correções do combustível pelo Shell. POR PADRÃO É SÓ SIMULAÇÃO (não grava).

Cada correção só roda se você pedir com a opção correspondente. Sem --gravar,
tudo é feito dentro de uma transação que é DESFEITA no final, e o script mostra
o saldo que ficaria.

Exemplos (pasta do projeto, no Shell do Render):

  # 1) simular tudo que está decidido:
  python corrigir_combustivel.py --apagar-testes --apagar-ajustes-legados \\
      --nf003 corrigir --numero-180633 --entrada-1181288 2026-10-19

  # 2) se o resultado estiver certo, repita o MESMO comando com --gravar no fim.

Opções:
  --apagar-testes             apaga as NFs de teste: 3x "001" (06/10, 1 L),
                              "01 teste" (14/10, 1 L) e "0001" (20/10, 35 L)
  --apagar-ajustes-legados    apaga os ajustes de outubro SEM saldo físico
                              (os dois de -37.521,27 L). NÃO mexe na aferição
                              de 6.900 L.
  --nf003 corrigir|apagar     NF 003 (20/10): corrigir = total R$ 6.780,00 e
                              R$/L 6,78; apagar = exclui a NF
  --numero-180633             troca o número da NF 180633 (08/10) para 1180633
  --entrada-1181288 AAAA-MM-DD  muda a data FÍSICA de entrada da NF 1181288
                              (a data fiscal não é alterada)
  --gravar                    grava de verdade (sem isto, só simula)

Antes de usar --gravar, faça um backup do banco no painel do Render.
"""
import argparse
import os
import sys
from datetime import date

os.environ["AGENDADOR_ATIVO"] = "0"
os.environ["ALERTAS_EMAIL_ATIVO"] = "0"

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import AjusteEstoqueCombustivel, NotaFiscalCombustivel  # noqa: E402
from services.crud import ErroNegocio, registrar_log  # noqa: E402
from services.estoque_combustivel import recalcular_estoque_combustivel  # noqa: E402

COMB = "Diesel S10"


def br(v, c=2):
    return f"{v or 0:,.{c}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def achar_nfs(numero, entrada=None, litros_max=None):
    q = NotaFiscalCombustivel.query.filter(NotaFiscalCombustivel.numero_nf == numero,
                                           NotaFiscalCombustivel.combustivel == COMB)
    notas = q.all()
    if entrada:
        notas = [n for n in notas if (n.data_entrada or n.data) == entrada]
    if litros_max is not None:
        notas = [n for n in notas if (n.litros or 0) <= litros_max]
    return notas


def apagar_nf(n, motivo):
    print(f"  - apagando NF {n.numero_nf} de {(n.data_entrada or n.data):%d/%m} "
          f"({br(n.litros)} L, R$ {br(n.valor_total)}) [{motivo}]")
    registrar_log("excluir", "notas_combustivel", n.id, f"NF {n.numero_nf} (shell: {motivo})")
    db.session.delete(n)


def main(a):
    feito = 0

    if a.apagar_testes:
        print("\n[Testes]")
        alvo = (achar_nfs("001", date(2026, 10, 6), 1.5)
                + achar_nfs("01 teste", date(2026, 10, 14), 1.5)
                + achar_nfs("0001", date(2026, 10, 20), 35.5))
        if not alvo:
            print("  nada encontrado (talvez já apagadas).")
        for n in alvo:
            apagar_nf(n, "NF de teste")
            feito += 1

    if a.nf003:
        print("\n[NF 003]")
        notas = achar_nfs("003", date(2026, 10, 20))
        if not notas:
            print("  NF 003 não encontrada.")
        for n in notas:
            if a.nf003 == "apagar":
                apagar_nf(n, "NF 003 era teste")
            else:
                print(f"  - NF 003: total {br(n.valor_total)} -> 6.780,00 ; R$/L {br(n.valor_litro, 4)} -> 6,7800")
                n.valor_total = 6780.00
                n.valor_litro = 6.78
                registrar_log("editar", "notas_combustivel", n.id, "NF 003: total corrigido para 6780,00 (shell)")
            feito += 1

    if a.numero_180633:
        print("\n[NF 180633]")
        notas = achar_nfs("180633", date(2026, 10, 8))
        if not notas:
            print("  NF 180633 não encontrada.")
        for n in notas:
            print("  - número 180633 -> 1180633")
            n.numero_nf = "1180633"
            registrar_log("editar", "notas_combustivel", n.id, "NF 180633 renumerada para 1180633 (shell)")
            feito += 1

    if a.entrada_1181288:
        print("\n[NF 1181288]")
        nova = date.fromisoformat(a.entrada_1181288)
        notas = achar_nfs("1181288")
        if not notas:
            print("  NF 1181288 não encontrada.")
        for n in notas:
            print(f"  - data de entrada {(n.data_entrada or n.data):%d/%m/%Y} -> {nova:%d/%m/%Y} "
                  f"(data fiscal {n.data:%d/%m/%Y} não muda)")
            n.data_entrada = nova
            registrar_log("editar", "notas_combustivel", n.id,
                          f"NF 1181288: data de entrada -> {nova.isoformat()} (shell)")
            feito += 1

    if a.apagar_ajustes_legados:
        print("\n[Ajustes legados]")
        ajs = (AjusteEstoqueCombustivel.query
               .filter(AjusteEstoqueCombustivel.combustivel == COMB,
                       AjusteEstoqueCombustivel.saldo_fisico.is_(None),
                       AjusteEstoqueCombustivel.data >= date(2026, 10, 1),
                       AjusteEstoqueCombustivel.data <= date(2026, 10, 31)).all())
        if not ajs:
            print("  nenhum encontrado.")
        for aj in ajs:
            print(f"  - apagando ajuste id {aj.id} de {aj.data:%d/%m} ({br(aj.litros)} L, sem saldo físico)")
            registrar_log("excluir", "estoque_combustivel", aj.id, "ajuste legado sem saldo físico (shell)")
            db.session.delete(aj)
            feito += 1

    if not feito:
        print("\nNenhuma correção pedida. Veja as opções com --help.")
        return False

    db.session.flush()
    print("\n[Recalculando o kardex]")
    try:
        r = recalcular_estoque_combustivel(COMB, estrito=True)
    except ErroNegocio as e:
        print(f"  ERRO: {e}")
        print("  Nada foi gravado.")
        return False
    print(f"  Comprado : {br(r.get('litros_comprados'))} L")
    print(f"  Consumido: {br(r.get('litros_consumidos'))} L")
    print(f"  Saldo    : {br(r.get('litros_estoque'))} L | R$ {br(r.get('valor_estoque'))} "
          f"| custo médio R$ {br(r.get('custo_medio'), 4)}")
    print(f"  Alertas  : {len(r.get('alertas') or [])}")
    for al in r.get("alertas") or []:
        print(f"    - {al}")
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Correções do combustível (simulação por padrão).")
    p.add_argument("--apagar-testes", action="store_true")
    p.add_argument("--apagar-ajustes-legados", action="store_true")
    p.add_argument("--nf003", choices=["corrigir", "apagar"])
    p.add_argument("--numero-180633", action="store_true")
    p.add_argument("--entrada-1181288", metavar="AAAA-MM-DD")
    p.add_argument("--gravar", action="store_true")
    args = p.parse_args()

    with app.app_context(), app.test_request_context():
        from flask import session
        session["usuario_nome"] = "shell"
        ok = False
        try:
            ok = main(args)
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            print(f"\nFalhou ({e.__class__.__name__}): {e}\nNada foi gravado.")
            sys.exit(1)
        if ok and args.gravar:
            db.session.commit()
            print("\nGRAVADO.")
        else:
            db.session.rollback()
            print("\nSIMULAÇÃO: nada foi gravado." if ok else "")
