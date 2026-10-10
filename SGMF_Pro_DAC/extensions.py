"""Extensões compartilhadas pela aplicação."""
import sqlite3

from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _ativar_chaves_estrangeiras(conexao, _registro):
    """O SQLite ignora chaves estrangeiras por padrão.

    Sem isso, apagar um veículo deixaria abastecimentos e ordens órfãos no
    desenvolvimento — e o mesmo comando falharia no PostgreSQL da produção.
    Ligamos a verificação para que os dois ambientes se comportem igual.
    """
    if isinstance(conexao, sqlite3.Connection):
        cursor = conexao.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
