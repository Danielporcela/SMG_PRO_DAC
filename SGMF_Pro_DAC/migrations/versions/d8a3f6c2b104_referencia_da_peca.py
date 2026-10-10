"""referência da peça

Revision ID: d8a3f6c2b104
Revises: b7f2c1d4e890
Create Date: 2026-08-17 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d8a3f6c2b104"
down_revision = "b7f2c1d4e890"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    colunas = {coluna["name"] for coluna in inspetor.get_columns("pecas")}

    with op.batch_alter_table("pecas", schema=None) as batch_op:
        if "referencia" not in colunas:
            batch_op.add_column(sa.Column("referencia", sa.String(length=60), nullable=True))


def downgrade():
    with op.batch_alter_table("pecas", schema=None) as batch_op:
        batch_op.drop_column("referencia")
