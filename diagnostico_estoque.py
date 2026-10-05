"""Diagnóstico do valor do estoque. O relatório só faz consultas (SELECT).

Observação: ao abrir o app, o SGMF roda as mesmas rotinas de inicialização
de sempre (verificação de tabelas/colunas e sincronização de alertas), as
mesmas que rodam em cada deploy. Este script não acrescenta nenhuma escrita.

Como rodar (no Shell do Render, na pasta do projeto):

    python diagnostico_estoque.py

Responde: de onde vem o valor do indicador "Estoque" do painel, que é
    soma de (quantidade x custo unitário) de todas as peças.

O relatório separa o valor em partes para você ver o que é real e o que
pode estar inflado:
  1. peças já lançadas em OS que ainda NÃO foram finalizadas (a baixa só
     acontece quando a OS é finalizada);
  2. OS finalizadas cuja baixa ficou pendente (Auditoria de estoque das OS);
  3. peças com saldo MAIOR do que tudo o que já entrou menos o que saiu;
  4. as peças de maior valor e valores atípicos (custo ou quantidade
     digitados errado costumam aparecer aqui).
"""
import os
from collections import defaultdict

# Importar o app já o inicializa (app.py cria o app ao ser importado). Estas
# duas linhas impedem que ESTE processo ligue o agendador de alertas ou envie
# e-mails; o serviço web do Render não é afetado. Precisam vir antes do import.
os.environ["AGENDADOR_ATIVO"] = "0"
os.environ["ALERTAS_EMAIL_ATIVO"] = "0"

from sqlalchemy import func

from app import app
from extensions import db
from models import ItemOS, MovimentoEstoque, OrdemServico, Peca, PecaSerial


def moeda(v):
    s = f"{abs(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if (v or 0) < 0 else ''}R$ {s}"


def num(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")


def titulo(texto):
    print("\n" + "=" * 78)
    print(texto)
    print("=" * 78)


def main():
    pecas = Peca.query.all()
    por_id = {p.id: p for p in pecas}
    valor = lambda p: (p.quantidade or 0) * (p.custo_unitario or 0)  # noqa: E731
    total = sum(valor(p) for p in pecas)

    titulo("1) VALOR DO INDICADOR 'ESTOQUE' (o mesmo cálculo do painel)")
    print(f"Peças cadastradas: {len(pecas)} | com saldo > 0: {sum(1 for p in pecas if (p.quantidade or 0) > 0)}")
    print(f"Valor total em estoque: {moeda(total)}")
    negativas = [p for p in pecas if (p.quantidade or 0) < 0]
    if negativas:
        print(f"ATENÇÃO: {len(negativas)} peça(s) com saldo NEGATIVO (distorcem o total).")

    # ---------------------------------------------------------------- 2
    titulo("2) PEÇAS LANÇADAS EM OS AINDA NÃO FINALIZADAS (baixa só ocorre ao finalizar)")
    abertas = (db.session.query(ItemOS, OrdemServico)
               .join(OrdemServico, ItemOS.ordem_servico_id == OrdemServico.id)
               .filter(OrdemServico.status != "Finalizada", ItemOS.peca_id.isnot(None),
                       ItemOS.baixado_estoque.isnot(True)).all())
    qtd_aberta = defaultdict(float)
    os_por_status = defaultdict(set)
    for item, ordem in abertas:
        qtd_aberta[item.peca_id] += float(item.quantidade or 0)
        os_por_status[ordem.status].add(ordem.id)
    valor_aberto = sum(q * (por_id[pid].custo_unitario or 0) for pid, q in qtd_aberta.items() if pid in por_id)
    print(f"Itens de peça em OS abertas: {len(abertas)} | OS envolvidas: "
          f"{len(set().union(*os_por_status.values())) if os_por_status else 0}")
    for status, ids in sorted(os_por_status.items()):
        print(f"   - {status}: {len(ids)} OS")
    print(f"Valor já consumido na prática mas ainda dentro do estoque: {moeda(valor_aberto)}")
    print("   (some quando a OS for finalizada)")

    # ---------------------------------------------------------------- 3
    titulo("3) OS FINALIZADAS COM BAIXA PENDENTE (o estoque NÃO foi abatido)")
    pend = (db.session.query(ItemOS, OrdemServico)
            .join(OrdemServico, ItemOS.ordem_servico_id == OrdemServico.id)
            .filter(OrdemServico.status == "Finalizada", ItemOS.peca_id.isnot(None),
                    ItemOS.baixado_estoque.isnot(True)).all())
    qtd_pend = defaultdict(float)
    for item, _ordem in pend:
        qtd_pend[item.peca_id] += float(item.quantidade or 0)
    valor_pend = sum(q * (por_id[pid].custo_unitario or 0) for pid, q in qtd_pend.items() if pid in por_id)
    print(f"OS finalizadas com baixa pendente: {len({o.id for _, o in pend})} | itens: {len(pend)}")
    print(f"Valor que deveria ter saído do estoque e não saiu: {moeda(valor_pend)}")
    if pend:
        print("   -> Regularize em: menu Auditoria de estoque das OS.")

    # ---------------------------------------------------------------- 4
    titulo("4) PEÇAS COM SALDO MAIOR DO QUE O HISTÓRICO PERMITE")
    mov = defaultdict(lambda: defaultdict(float))
    for peca_id, tipo, q in (db.session.query(MovimentoEstoque.peca_id, MovimentoEstoque.tipo,
                                              func.sum(MovimentoEstoque.quantidade))
                             .group_by(MovimentoEstoque.peca_id, MovimentoEstoque.tipo).all()):
        mov[peca_id][tipo] = float(q or 0)
    # Peças cadastradas já com saldo inicial por número de série não geram
    # movimento de entrada comum: contamos só as unidades de "Cadastro manual".
    series_cadastro = defaultdict(int)
    for peca_id, n in (db.session.query(PecaSerial.peca_id, func.count(PecaSerial.id))
                       .filter(PecaSerial.origem == "Cadastro manual")
                       .group_by(PecaSerial.peca_id).all()):
        series_cadastro[peca_id] = n

    suspeitas = []
    for p in pecas:
        m = mov[p.id]
        if m.get("ajuste"):
            continue  # ajuste manual redefine o saldo: não dá para conferir só pelo histórico
        maximo = m.get("entrada", 0) + series_cadastro[p.id] - m.get("saida", 0)
        excesso = (p.quantidade or 0) - maximo
        if excesso > 0.001:
            suspeitas.append((excesso * (p.custo_unitario or 0), p, excesso, maximo))
    suspeitas.sort(key=lambda x: -x[0])
    if not suspeitas:
        print("Nenhuma peça com saldo acima do histórico de entradas menos saídas.")
    else:
        print(f"{len(suspeitas)} peça(s) com saldo acima do que as entradas menos as saídas explicam "
              f"(possível saldo inicial digitado a mais ou baixa que não ocorreu).")
        print(f"Valor possivelmente inflado por isso: {moeda(sum(s[0] for s in suspeitas))}")
        print(f"{'Código':<10}{'Peça':<34}{'Saldo':>10}{'Esperado':>10}{'Sobra':>9}{'Valor':>16}")
        for v, p, excesso, maximo in suspeitas[:20]:
            print(f"{p.codigo:<10}{(p.descricao or '')[:32]:<34}{num(p.quantidade or 0):>10}"
                  f"{num(maximo):>10}{num(excesso):>9}{moeda(v):>16}")
        if len(suspeitas) > 20:
            print(f"... e mais {len(suspeitas) - 20}.")

    # ---------------------------------------------------------------- 5
    titulo("5) AS 15 PEÇAS DE MAIOR VALOR EM ESTOQUE")
    maiores = sorted(pecas, key=valor, reverse=True)[:15]
    acumulado = sum(valor(p) for p in maiores)
    print(f"Elas somam {moeda(acumulado)} ({(acumulado / total * 100) if total else 0:.0f}% do total).")
    print(f"{'Código':<10}{'Peça':<34}{'Saldo':>10}{'Custo un.':>14}{'Valor':>16}")
    for p in maiores:
        print(f"{p.codigo:<10}{(p.descricao or '')[:32]:<34}{num(p.quantidade or 0):>10}"
              f"{moeda(p.custo_unitario):>14}{moeda(valor(p)):>16}")

    # ---------------------------------------------------------------- 6
    titulo("6) VALOR POR GRUPO")
    por_grupo = defaultdict(float)
    for p in pecas:
        por_grupo[p.grupo or "(sem grupo)"] += valor(p)
    for grupo, v in sorted(por_grupo.items(), key=lambda x: -x[1]):
        print(f"{grupo:<28}{moeda(v):>18}")

    # ---------------------------------------------------------------- resumo
    titulo("RESUMO")
    print(f"Valor em estoque hoje ........................ {moeda(total)}")
    print(f"  - já consumido em OS ainda abertas ......... {moeda(valor_aberto)}")
    print(f"  - OS finalizadas sem baixa ................. {moeda(valor_pend)}")
    print(f"  - saldo acima do histórico ................. {moeda(sum(s[0] for s in suspeitas))}")
    print("As três linhas acima podem se sobrepor em parte; use como pistas, não como soma exata.")


if __name__ == "__main__":
    with app.app_context():
        main()
