"""Cria as tabelas do módulo de ordens de compra no banco já existente.

Rode uma única vez, na raiz do projeto (a mesma pasta do app.py):

    python migrar_ordens_compra.py

É seguro rodar de novo: se as tabelas já existirem, nada é alterado
(checkfirst=True). Nenhuma tabela antiga é tocada — só são criadas
`ordens_compra` e `itens_ordem_compra`.
"""
import sys

from extensions import db
from models import ItemOrdemCompra, OrdemCompra


def obter_app():
    """Funciona tanto com `app = Flask(...)` no app.py quanto com fábrica."""
    import app as modulo_app
    if hasattr(modulo_app, "app"):
        return modulo_app.app
    if hasattr(modulo_app, "create_app"):
        return modulo_app.create_app()
    raise SystemExit("Não encontrei 'app' nem 'create_app' no app.py — "
                     "ajuste a função obter_app() deste script.")


def main():
    app = obter_app()
    with app.app_context():
        existentes = set(db.inspect(db.engine).get_table_names())
        for modelo in (OrdemCompra, ItemOrdemCompra):
            nome = modelo.__tablename__
            if nome in existentes:
                print(f"· {nome}: já existe, nada a fazer")
                continue
            modelo.__table__.create(db.engine, checkfirst=True)
            print(f"✓ {nome}: criada")
    print("\nPronto. Abra o sistema em Cadastros › Usuários para liberar a tela "
          "'Ordens de compra' para quem vai solicitar e para quem vai aprovar.")


if __name__ == "__main__":
    sys.exit(main())
