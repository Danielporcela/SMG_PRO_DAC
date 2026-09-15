"""merge antes da correcao de permissoes

Revision ID: d09ef6a77750
Revises: c4a1e9f2b736, d1f5b8a3c942
Create Date: 2026-09-15 03:55:53.312567

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd09ef6a77750'
down_revision = ('c4a1e9f2b736', 'd1f5b8a3c942')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
