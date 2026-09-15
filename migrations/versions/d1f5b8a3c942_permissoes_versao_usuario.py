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


def upgrade():
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('permissoes_versao', sa.Integer(),
                                       nullable=False, server_default='0'))


def downgrade():
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('permissoes_versao')
