"""cco, solicitante, setor, problema e local de execucao na OS

Revision ID: d3f6b91a2c58
Revises: c7a19f4e6b3d
Create Date: 2026-08-27 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "d3f6b91a2c58"
down_revision = "c7a19f4e6b3d"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    colunas = {coluna["name"] for coluna in inspetor.get_columns("ordens_servico")}

    novas = {
        "cco": sa.String(length=40),
        "solicitante": sa.String(length=120),
        "setor": sa.String(length=60),
        "problema": sa.Text(),
        "local_execucao": sa.String(length=20),
    }

    with op.batch_alter_table("ordens_servico", schema=None) as batch_op:
        for nome, tipo in novas.items():
            if nome not in colunas:
                batch_op.add_column(sa.Column(nome, tipo, nullable=True))


def downgrade():
    with op.batch_alter_table("ordens_servico", schema=None) as batch_op:
        batch_op.drop_column("local_execucao")
        batch_op.drop_column("problema")
        batch_op.drop_column("setor")
        batch_op.drop_column("solicitante")
        batch_op.drop_column("cco")
