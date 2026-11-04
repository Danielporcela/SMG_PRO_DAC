"""parcelas (boletos) da nota fiscal de entrada

Revision ID: d5f1b8c3a926
Revises: c9e4a7b2d158
Create Date: 2026-11-04 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d5f1b8c3a926"
down_revision = "c9e4a7b2d158"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "parcelas_nota_fiscal" in sa.inspect(bind).get_table_names():
        return   # já criada por garantir_parcelas_nota_fiscal() na inicialização
    op.create_table(
        "parcelas_nota_fiscal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nota_fiscal_id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=True),
        sa.Column("data_vencimento", sa.Date(), nullable=False),
        sa.Column("valor", sa.Float(), nullable=True),
        sa.Column("pago", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("data_pagamento", sa.Date(), nullable=True),
        sa.Column("pago_por", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["nota_fiscal_id"], ["notas_fiscais.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parcelas_nota_fiscal_nota_fiscal_id", "parcelas_nota_fiscal", ["nota_fiscal_id"])
    op.create_index("ix_parcelas_nota_fiscal_data_vencimento", "parcelas_nota_fiscal", ["data_vencimento"])


def downgrade():
    op.drop_index("ix_parcelas_nota_fiscal_data_vencimento", table_name="parcelas_nota_fiscal")
    op.drop_index("ix_parcelas_nota_fiscal_nota_fiscal_id", table_name="parcelas_nota_fiscal")
    op.drop_table("parcelas_nota_fiscal")
