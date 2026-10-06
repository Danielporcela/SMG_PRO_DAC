# -*- coding: utf-8 -*-
"""Importa as NOTAS FISCAIS DE COMBUSTÍVEL da planilha ABASTECIMENTOS_<MÊS>.xlsx
para o SGMF Pro DAC (tabela notas_fiscais_combustivel).

Colunas esperadas na planilha (linha 1 = cabeçalho):
    DATA | NUMERO NOTA FISCAL | FORNECEDOR | QUANTIDADE LITROS | VALOR DO LITRO | VALORES TOTAL

Regras (as mesmas da tela Abastecimentos > Nota fiscal):
  * Cada NF vira uma ENTRADA no estoque de combustível (litros + valor).
  * Linhas repetidas da mesma NF + mesmo fornecedor são somadas numa única NF.
  * O valor TOTAL da nota prevalece; o valor do litro é recalculado (total / litros).
  * Fornecedor é localizado pelo nome; se não existir, é cadastrado.
  * Ativa o controle de estoque do combustível na data da 1ª NF e recalcula o
    kardex. Se faltar saldo para algum abastecimento já lançado, NADA é gravado.
  * É seguro rodar de novo: NF que já existe (mesmo número + fornecedor + data)
    é pulada.

Por padrão roda em modo CONFERÊNCIA (não grava). Só grava com --commit.

Uso (na raiz do projeto, mesma pasta do app.py):
    python importar_nf_combustivel_planilha.py ABASTECIMENTOS_SETEMBRO.xlsx
    python importar_nf_combustivel_planilha.py ABASTECIMENTOS_SETEMBRO.xlsx --commit
    (também aceita .csv com ; como separador, datas AAAA-MM-DD e ponto decimal)
    python importar_nf_combustivel_planilha.py ABASTECIMENTOS_SETEMBRO.xlsx --combustivel "Diesel S500" --commit
"""
import argparse
import shutil
import sys
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

COMBUSTIVEL_PADRAO = "Diesel S10"


# --------------------------------------------------------------------------
# Leitura da planilha (não depende do Flask)
# --------------------------------------------------------------------------
def _data(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
            try:
                return datetime.strptime(v.strip(), fmt).date()
            except ValueError:
                pass
    return None


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def ler_notas(caminho):
    """Devolve (notas, avisos). `notas` = lista de dicts já consolidada por NF."""
    if str(caminho).lower().endswith(".csv"):
        import csv
        with open(caminho, newline="", encoding="utf-8-sig") as fh:
            amostra = fh.read(2048)
            fh.seek(0)
            sep = ";" if amostra.count(";") >= amostra.count(",") else ","
            linhas = [tuple(c if c != "" else None for c in r) for r in csv.reader(fh, delimiter=sep)]
    else:
        wb = load_workbook(caminho, data_only=True)
        ws = wb.active
        linhas = list(ws.iter_rows(values_only=True))
    if not linhas:
        raise SystemExit("Planilha vazia.")

    cab = [str(c).strip().upper() if c else "" for c in linhas[0]]

    def achar(*pistas):
        for i, nome in enumerate(cab):
            if all(p in nome for p in pistas):
                return i
        raise SystemExit(f"Coluna não encontrada: {' '.join(pistas)}. Cabeçalho lido: {cab}")

    i_data = achar("DATA")
    i_nf = achar("NOTA")
    i_forn = achar("FORNECEDOR")
    i_lit = achar("LITROS")
    i_unit = achar("VALOR", "LITRO")
    i_total = achar("TOTAL")

    avisos = []
    notas = OrderedDict()
    for n, lin in enumerate(linhas[1:], start=2):
        if all(c is None for c in lin):
            continue
        nf = lin[i_nf]
        if nf is None or str(nf).strip() == "":
            avisos.append(f"Linha {n}: sem número de NF — ignorada.")
            continue
        nf = str(int(nf)) if isinstance(nf, (int, float)) else str(nf).strip()
        d = _data(lin[i_data])
        forn = (str(lin[i_forn]).strip() if lin[i_forn] else "")
        litros = _num(lin[i_lit])
        unit = _num(lin[i_unit])
        total = _num(lin[i_total])
        if not d or not forn or not litros or litros <= 0:
            avisos.append(f"Linha {n} (NF {nf}): data/fornecedor/litros inválidos — ignorada.")
            continue
        if not total and unit:
            total = round(litros * unit, 2)
        if not total or total <= 0:
            avisos.append(f"Linha {n} (NF {nf}): sem valor — ignorada.")
            continue

        chave = (nf, forn.upper(), d)
        if chave in notas:
            notas[chave]["litros"] += litros
            notas[chave]["valor_total"] += total
            notas[chave]["linhas"] += 1
        else:
            notas[chave] = {"numero_nf": nf, "fornecedor": forn, "data": d,
                            "litros": litros, "valor_total": total, "linhas": 1}

    saida = []
    for nota in notas.values():
        nota["litros"] = round(nota["litros"], 3)
        nota["valor_total"] = round(nota["valor_total"], 2)
        nota["valor_litro"] = round(nota["valor_total"] / nota["litros"], 4)
        saida.append(nota)
    return saida, avisos


# --------------------------------------------------------------------------
# Gravação no sistema
# --------------------------------------------------------------------------
def obter_app():
    import app as modulo_app
    if hasattr(modulo_app, "app"):
        return modulo_app.app
    for nome in ("create_app", "criar_app"):
        if hasattr(modulo_app, nome):
            return getattr(modulo_app, nome)()
    raise SystemExit("Não encontrei 'app' nem função de fábrica no app.py.")


def _tipo_fornecedor(nome):
    n = nome.upper()
    return "Posto" if ("SIGARAN" in n or "POSTO" in n) else "Fornecedor"


def importar(notas, combustivel, gravar):
    from extensions import db
    from models import Fornecedor, NotaFiscalCombustivel
    from services.crud import ErroNegocio
    from services.estoque_combustivel import ativar_controle, recalcular_estoque_combustivel

    novas, puladas, forn_criados = [], [], []
    cache_forn = {}

    def fornecedor(nome):
        chave = nome.upper()
        if chave in cache_forn:
            return cache_forn[chave]
        f = next((x for x in Fornecedor.query.all()
                  if (x.nome or "").strip().upper() == chave), None)
        if not f:
            f = Fornecedor(nome=nome, tipo=_tipo_fornecedor(nome), ativo=True)
            db.session.add(f)
            db.session.flush()
            forn_criados.append(nome)
        cache_forn[chave] = f
        return f

    try:
        for n in notas:
            f = fornecedor(n["fornecedor"])
            existe = NotaFiscalCombustivel.query.filter_by(
                numero_nf=n["numero_nf"], fornecedor_id=f.id, data=n["data"]).first()
            if existe:
                puladas.append(n)
                continue
            db.session.add(NotaFiscalCombustivel(
                numero_nf=n["numero_nf"], data=n["data"], data_entrada=n["data"],
                fornecedor_id=f.id, combustivel=combustivel,
                litros=n["litros"], valor_litro=n["valor_litro"],
                valor_total=n["valor_total"],
                observacao="Importada da planilha de abastecimentos"))
            novas.append(n)
        db.session.flush()

        if novas:
            ativar_controle(combustivel, min(n["data"] for n in novas))
            resumo = recalcular_estoque_combustivel(combustivel)
        else:
            resumo = None

        if gravar:
            db.session.commit()
        else:
            db.session.rollback()
        return novas, puladas, forn_criados, resumo
    except ErroNegocio as e:
        db.session.rollback()
        raise SystemExit(f"\nNADA foi gravado. O sistema recusou: {e}")
    except Exception:
        db.session.rollback()
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("planilha")
    ap.add_argument("--commit", action="store_true", help="grava de verdade (sem isto é só conferência)")
    ap.add_argument("--combustivel", default=COMBUSTIVEL_PADRAO,
                    help=f"tipo de combustível das NFs (padrão: {COMBUSTIVEL_PADRAO})")
    args = ap.parse_args()

    caminho = Path(args.planilha)
    if not caminho.exists():
        raise SystemExit(f"Arquivo não encontrado: {caminho}")

    notas, avisos = ler_notas(caminho)
    for a in avisos:
        print("  Aviso:", a)

    por_forn = OrderedDict()
    for n in notas:
        x = por_forn.setdefault(n["fornecedor"], [0, 0.0, 0.0])
        x[0] += 1; x[1] += n["litros"]; x[2] += n["valor_total"]
    print(f"\nPlanilha: {len(notas)} NF(s) a importar como {args.combustivel}")
    for forn, (q, l, v) in por_forn.items():
        print(f"  {forn:<50} {q:>3} NF  {l:>12,.2f} L  R$ {v:>14,.2f}")
    print(f"  {'TOTAL':<50} {len(notas):>3} NF  {sum(n['litros'] for n in notas):>12,.2f} L  "
          f"R$ {sum(n['valor_total'] for n in notas):>14,.2f}")

    app = obter_app()
    with app.app_context():
        from extensions import db
        uri = str(db.engine.url)
        if args.commit and uri.startswith("sqlite"):
            arq = Path(db.engine.url.database)
            if arq.exists():
                bkp = arq.with_name(arq.name + f".backup_{datetime.now():%Y%m%d_%H%M%S}")
                shutil.copy2(arq, bkp)
                print(f"\nBackup do banco: {bkp}")

        novas, puladas, forn_criados, resumo = importar(notas, args.combustivel, args.commit)

    print("\n" + ("GRAVADO." if args.commit else "CONFERÊNCIA (nada foi gravado — use --commit)."))
    print(f"  NFs novas: {len(novas)} | já existentes (puladas): {len(puladas)}")
    if forn_criados:
        print("  Fornecedores cadastrados:", ", ".join(forn_criados))
    if resumo:
        print(f"  Estoque {args.combustivel} após o kardex: {resumo['litros_estoque']:,.2f} L "
              f"(custo médio R$ {resumo['custo_medio']:.4f}/L)")


if __name__ == "__main__":
    sys.exit(main())
