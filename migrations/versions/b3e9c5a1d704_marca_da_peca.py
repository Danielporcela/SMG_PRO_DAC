"""marca da peça

Revision ID: b3e9c5a1d704
Revises: e7a3c9d1b405
Create Date: 2026-10-29 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3e9c5a1d704"
down_revision = "e7a3c9d1b405"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    colunas = {coluna["name"] for coluna in inspetor.get_columns("pecas")}

    with op.batch_alter_table("pecas", schema=None) as batch_op:
        if "marca" not in colunas:
            batch_op.add_column(sa.Column("marca", sa.String(length=60), nullable=True))


def downgrade():
    with op.batch_alter_table("pecas", schema=None) as batch_op:
        batch_op.drop_column("marca")
