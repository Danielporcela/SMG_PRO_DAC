"""adiciona permissoes_versao ao usuario (invalida sessao ao mudar permissao)

Revision ID: d1f5b8a3c942
Revises: c4d8e2a6f713
Create Date: 2026-09-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd1f5b8a3c942'
down_revision = 'c4d8e2a6f713'
branch_labels = None
depends_on = None


def _tem_coluna(tabela, coluna):
    """Evita erro 'column already exists': esta migration e a
    c4a1e9f2b736 (outro ramo do histórico, unido depois em d09ef6a77750)
    adicionam a mesma coluna de forma independente. Sem essa checagem,
    o `flask db upgrade` falha na segunda tentativa e trava todo o
    restante das migrations pendentes."""
    insp = sa.inspect(op.get_bind())
    return coluna in [c["name"] for c in insp.get_columns(tabela)]


def upgrade():
    if _tem_coluna('usuarios', 'permissoes_versao'):
        return
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('permissoes_versao', sa.Integer(),
                                       nullable=False, server_default='0'))


def downgrade():
    if not _tem_coluna('usuarios', 'permissoes_versao'):
        return
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('permissoes_versao')
