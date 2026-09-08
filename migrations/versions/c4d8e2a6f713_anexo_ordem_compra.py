"""anexo na ordem de compra

Revision ID: c4d8e2a6f713
Revises: a2f7e6c1b930
Create Date: 2026-09-08 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d8e2a6f713'
down_revision = 'a2f7e6c1b930'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    colunas = {c["name"] for c in inspetor.get_columns("anexos")}
    with op.batch_alter_table('anexos', schema=None) as batch_op:
        if 'ordem_compra_id' not in colunas:
            batch_op.add_column(sa.Column('ordem_compra_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_anexos_ordem_compra_id', 'ordens_compra',
                                         ['ordem_compra_id'], ['id'])


def downgrade():
    with op.batch_alter_table('anexos', schema=None) as batch_op:
        batch_op.drop_constraint('fk_anexos_ordem_compra_id', type_='foreignkey')
        batch_op.drop_column('ordem_compra_id')
