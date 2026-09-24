"""Cria a tabela de licenciamento por módulo no banco já existente.

Rode uma única vez, na raiz do projeto (a mesma pasta do app.py):

    python migrar_licencas.py

(no Render, pelo Shell do serviço, já que é lá que fica o Postgres.)

É seguro rodar de novo: se a tabela já existir, nada é alterado
(checkfirst=True). Nenhuma tabela antiga é tocada — só é criada
`licencas`, e o módulo "administrativo" entra travado (liberado=False)
até você rodar `flask licenca liberar administrativo`.
"""
import sys

from extensions import db
from models import Licenca


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
        if "licencas" in existentes:
            print("· licencas: já existe, nada a fazer")
        else:
            Licenca.__table__.create(db.engine, checkfirst=True)
            print("✓ licencas: criada")

        if not Licenca.query.filter_by(modulo="administrativo").first():
            db.session.add(Licenca(modulo="administrativo", liberado=False))
            db.session.commit()
            print("✓ módulo 'administrativo' cadastrado como TRAVADO "
                  "(liberado=False)")
        else:
            print("· módulo 'administrativo' já tinha registro, nada a fazer")

    print("\nPronto. O módulo administrativo (Usuários, Auditoria, "
          "Notificações) fica travado para esta empresa até você rodar:\n"
          "    flask licenca liberar administrativo")


if __name__ == "__main__":
    sys.exit(main())
