"""Boletos vinculados às notas fiscais de uniformes.

Revision ID: f6b2c9d4e810
Revises: f4a7b8c9d012
"""
from alembic import op
import sqlalchemy as sa

revision = "f6b2c9d4e810"
down_revision = ("b3e9c5a1d704", "c4a1e9f2b736")
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "parcelas_nota_fiscal_uniforme" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "parcelas_nota_fiscal_uniforme",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nota_fiscal_uniforme_id", sa.Integer(), nullable=False),
            sa.Column("numero", sa.Integer(), nullable=True),
            sa.Column("data_vencimento", sa.Date(), nullable=False),
            sa.Column("valor", sa.Float(), nullable=True),
            sa.Column("pago", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("data_pagamento", sa.Date(), nullable=True),
            sa.Column("pago_por", sa.String(length=120), nullable=True),
            sa.ForeignKeyConstraint(["nota_fiscal_uniforme_id"], ["notas_fiscais_uniforme.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_parcelas_nota_fiscal_uniforme_nota_fiscal_uniforme_id", "parcelas_nota_fiscal_uniforme", ["nota_fiscal_uniforme_id"])
        op.create_index("ix_parcelas_nota_fiscal_uniforme_data_vencimento", "parcelas_nota_fiscal_uniforme", ["data_vencimento"])


def downgrade():
    op.drop_table("parcelas_nota_fiscal_uniforme")
