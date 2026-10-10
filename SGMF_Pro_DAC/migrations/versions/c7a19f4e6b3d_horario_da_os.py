"""horário de início e fim do serviço na OS

Revision ID: c7a19f4e6b3d
Revises: f3c1f82db64f
Create Date: 2026-08-27 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "c7a19f4e6b3d"
down_revision = "f3c1f82db64f"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    colunas = {coluna["name"] for coluna in inspetor.get_columns("ordens_servico")}

    with op.batch_alter_table("ordens_servico", schema=None) as batch_op:
        if "hora_inicio" not in colunas:
            batch_op.add_column(sa.Column("hora_inicio", sa.Time(), nullable=True))
        if "hora_fim" not in colunas:
            batch_op.add_column(sa.Column("hora_fim", sa.Time(), nullable=True))

    # O campo "grupo" já existe desde a estrutura inicial (migração
    # 4fb38b1f9382) — não precisa de coluna nova. Ele só passa a ser
    # preenchido agora, pelo novo select "Grupo do serviço" no formulário
    # de OS (Corretiva, Sistema mecânico, Borracharia, Hidráulico, Solda,
    # Preventiva, Elétrico, Acidente).


def downgrade():
    with op.batch_alter_table("ordens_servico", schema=None) as batch_op:
        batch_op.drop_column("hora_fim")
        batch_op.drop_column("hora_inicio")
