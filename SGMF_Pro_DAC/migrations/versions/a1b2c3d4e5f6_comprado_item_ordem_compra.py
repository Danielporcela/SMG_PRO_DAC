"""comprado no item da ordem de compra

Revision ID: a1b2c3d4e5f6
Revises: f3c1f82db64f
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f3c1f82db64f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('itens_ordem_compra', schema=None) as batch_op:
        batch_op.add_column(sa.Column('comprado', sa.Boolean(), nullable=False,
                                       server_default=sa.false()))
        batch_op.add_column(sa.Column('comprado_por', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('data_compra_item', sa.Date(), nullable=True))


def downgrade():
    with op.batch_alter_table('itens_ordem_compra', schema=None) as batch_op:
        batch_op.drop_column('data_compra_item')
        batch_op.drop_column('comprado_por')
        batch_op.drop_column('comprado')
