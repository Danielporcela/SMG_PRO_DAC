"""Cria a tabela do cadastro de grupos no banco que já existe.

Rode uma única vez, na raiz do projeto (a mesma pasta do app.py):

    python migrar_grupos.py

É seguro rodar de novo: se a tabela já existir, nada é alterado. Nenhuma
tabela antiga é tocada — só é criada `grupos`. Depois de criar, o script
importa automaticamente os grupos que já estão escritos nas peças (Elétrica,
Motor, Freios...), para o cadastro já nascer preenchido.
"""
import sys

from extensions import db
from models import Grupo, importar_grupos_das_pecas


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


def main():
    app = obter_app()
    with app.app_context():
        existentes = set(db.inspect(db.engine).get_table_names())
        if Grupo.__tablename__ in existentes:
            print(f"· {Grupo.__tablename__}: já existe, nada a fazer")
        else:
            Grupo.__table__.create(db.engine, checkfirst=True)
            print(f"✓ {Grupo.__tablename__}: criada")

        criados = importar_grupos_das_pecas()
        if criados:
            print(f"✓ {len(criados)} grupo(s) trazido(s) das peças:")
            for nome in criados:
                print(f"    - {nome}")
        else:
            print("· Nenhum grupo novo para importar das peças")

        print(f"\nTotal de grupos cadastrados: {Grupo.query.count()}")

    print("\nPronto. Abra o sistema em Cadastros › Grupos de peças.")
    print("Se algum usuário não enxergar a tela, libere a permissão 'Grupos de "
          "peças' em Cadastros › Usuários.")


if __name__ == "__main__":
    sys.exit(main())
