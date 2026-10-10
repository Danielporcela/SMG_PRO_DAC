"""Liga o controle de saldo POR TAMANHO no módulo de uniformes.

Rode uma única vez, na raiz do projeto (a mesma pasta do app.py):

    python migrar_uniformes_tamanho.py

O que ele faz:
  1. cria a tabela `saldos_uniforme` (uma linha por item + tamanho);
  2. acrescenta a coluna `tipo_tamanho` em `itens_uniforme`;
  3. acrescenta a coluna `tamanho` em `movimentos_uniforme`;
  4. cria as linhas de tamanho de cada item já cadastrado, zeradas, com o
     mínimo padrão do item.

Só acrescenta — nenhuma tabela, coluna ou registro é apagado. Rodar de novo é
seguro: o que já existir é deixado como está. Funciona igual no SQLite (local)
e no PostgreSQL (Render).
"""
import sys

from sqlalchemy import inspect, text

from extensions import db
from models import ItemUniforme, SaldoUniforme, garantir_saldos, recalcular_total_uniforme


def obter_app():
    """Funciona tanto com `app = Flask(...)` no app.py quanto com fábrica."""
    import app as modulo_app
    if hasattr(modulo_app, "app"):
        return modulo_app.app
    for nome in ("criar_app", "create_app"):
        if hasattr(modulo_app, nome):
            return getattr(modulo_app, nome)()
    raise SystemExit("Não encontrei 'app' nem 'criar_app' no app.py — "
                     "ajuste a função obter_app() deste script.")


def acrescentar_coluna(inspetor, tabela, coluna, definicao):
    existentes = {c["name"] for c in inspetor.get_columns(tabela)}
    if coluna in existentes:
        print(f"· {tabela}.{coluna}: já existe")
        return False
    db.session.execute(text(f'ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}'))
    db.session.commit()
    print(f"✓ {tabela}.{coluna}: criada")
    return True


def main():
    app = obter_app()
    with app.app_context():
        inspetor = inspect(db.engine)
        tabelas = set(inspetor.get_table_names())

        if "itens_uniforme" not in tabelas:
            raise SystemExit("A tabela 'itens_uniforme' não existe neste banco — "
                             "publique o módulo de uniformes antes de rodar isto.")

        # 1 e 2 — colunas novas nas tabelas antigas
        acrescentar_coluna(inspetor, "itens_uniforme", "tipo_tamanho", "VARCHAR(12)")
        if "movimentos_uniforme" in tabelas:
            acrescentar_coluna(inspetor, "movimentos_uniforme", "tamanho", "VARCHAR(10)")

        # 3 — tabela dos saldos por tamanho
        if SaldoUniforme.__tablename__ in tabelas:
            print(f"· {SaldoUniforme.__tablename__}: já existe")
        else:
            SaldoUniforme.__table__.create(db.engine, checkfirst=True)
            print(f"✓ {SaldoUniforme.__tablename__}: criada")

        # 4 — todo item ganha suas linhas de tamanho, zeradas
        itens = ItemUniforme.query.order_by(ItemUniforme.codigo).all()
        for item in itens:
            if not item.tipo_tamanho:
                item.tipo_tamanho = "roupa"   # padrão; ajuste no cadastro do item
            criados = garantir_saldos(item)
            anterior = item.quantidade or 0
            recalcular_total_uniforme(item)
            aviso = f"  (saldo antigo de {anterior:g} não foi distribuído)" if anterior else ""
            print(f"  · {item.codigo} {item.descricao}: {criados} tamanho(s){aviso}")
        db.session.commit()

        print(f"\nItens processados: {len(itens)}")

    print("\nPronto. Agora, na tela Uniformes:")
    print("  1. abra cada item e confira o campo 'Tipo de tamanho' (roupa, calçado ou único);")
    print("  2. no botão de tamanhos da linha, defina o mínimo de cada tamanho;")
    print("  3. lance as entradas do estoque escolhendo o tamanho.")


if __name__ == "__main__":
    sys.exit(main())
