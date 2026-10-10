"""adiciona horário de abertura e assinatura do mecânico na OS"""
from alembic import op
import sqlalchemy as sa

revision = "c2d4e6f8a901"
down_revision = "b8e1f4c7a902"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    colunas = {c["name"] for c in inspetor.get_columns("ordens_servico")}
    with op.batch_alter_table("ordens_servico", schema=None) as batch_op:
        if "hora_abertura" not in colunas:
            batch_op.add_column(sa.Column("hora_abertura", sa.Time(), nullable=True))
        if "assinatura_mecanico" not in colunas:
            batch_op.add_column(sa.Column("assinatura_mecanico", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("ordens_servico", schema=None) as batch_op:
        batch_op.drop_column("assinatura_mecanico")
        batch_op.drop_column("hora_abertura")
