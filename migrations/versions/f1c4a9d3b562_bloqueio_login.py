"""bloqueio de login por tentativas

Revision ID: f1c4a9d3b562
Revises: e5b8d1f0a237
Create Date: 2026-08-17 04:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "f1c4a9d3b562"
down_revision = "e5b8d1f0a237"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    tabelas = set(sa.inspect(bind).get_table_names())

    if "tentativas_login" not in tabelas:
        op.create_table(
            "tentativas_login",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("momento", sa.DateTime(), nullable=True),
            sa.Column("email_tentado", sa.String(length=120), nullable=True),
            sa.Column("ip", sa.String(length=45), nullable=True),
            sa.Column("sucesso", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    tabelas = set(sa.inspect(bind).get_table_names())

    if "bloqueios_acesso" not in tabelas:
        op.create_table(
            "bloqueios_acesso",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("tipo", sa.String(length=10), nullable=False),
            sa.Column("valor", sa.String(length=120), nullable=False),
            sa.Column("criado_em", sa.DateTime(), nullable=True),
            sa.Column("liberado", sa.Boolean(), nullable=True),
            sa.Column("liberado_por", sa.String(length=120), nullable=True),
            sa.Column("liberado_em", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    op.drop_table("bloqueios_acesso")
    op.drop_table("tentativas_login")
