"""orçamentos de fornecedor na ordem de compra

Revision ID: c9e4a7b2d158
Revises: b3e9c5a1d704
Create Date: 2026-11-03 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9e4a7b2d158"
down_revision = "b3e9c5a1d704"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "orcamentos_ordem_compra" in sa.inspect(bind).get_table_names():
        return   # já criada por garantir_orcamentos_compra() na inicialização
    op.create_table(
        "orcamentos_ordem_compra",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ordem_compra_id", sa.Integer(), nullable=False),
        sa.Column("fornecedor_id", sa.Integer(), nullable=True),
        sa.Column("fornecedor_nome", sa.String(length=120), nullable=True),
        sa.Column("valor_total", sa.Float(), nullable=True),
        sa.Column("prazo_entrega", sa.String(length=60), nullable=True),
        sa.Column("observacao", sa.String(length=200), nullable=True),
        sa.Column("escolhido", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("criado_por", sa.String(length=120), nullable=True),
        sa.Column("criado_em", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ordem_compra_id"], ["ordens_compra.id"]),
        sa.ForeignKeyConstraint(["fornecedor_id"], ["fornecedores.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orcamentos_ordem_compra_ordem_compra_id",
                    "orcamentos_ordem_compra", ["ordem_compra_id"])


def downgrade():
    op.drop_index("ix_orcamentos_ordem_compra_ordem_compra_id",
                  table_name="orcamentos_ordem_compra")
    op.drop_table("orcamentos_ordem_compra")
