"""merge heads

Revision ID: a9c8d7e6f501
Revises: a1b2c3d4e5f6, d3f6b91a2c58
Create Date: 2026-09-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a9c8d7e6f501'
down_revision = ('a1b2c3d4e5f6', 'd3f6b91a2c58')
branch_labels = None
depends_on = None


def upgrade():
    # Migração vazia: só une as duas pontas (ordens de compra e horário/campos
    # de painéis da OS) que foram criadas em paralelo a partir do mesmo ponto.
    pass


def downgrade():
    pass
