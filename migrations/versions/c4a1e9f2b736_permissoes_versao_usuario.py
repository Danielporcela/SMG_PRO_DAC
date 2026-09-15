"""adiciona permissoes_versao ao usuario (invalida sessao ao mudar permissao)

Revision ID: c4a1e9f2b736
Revises: b8e1f4c7a902
Create Date: 2026-09-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4a1e9f2b736'
down_revision = 'b8e1f4c7a902'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('permissoes_versao', sa.Integer(),
                                       nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('permissoes_versao')
