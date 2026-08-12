"""dados fiscais das peças e dos itens de nota

Revision ID: c2e91f8a6d45
Revises: b7f2a4c9e1d3
Create Date: 2026-08-09 17:50:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "c2e91f8a6d45"
down_revision = "b7f2a4c9e1d3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("pecas", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ncm", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("cfop_entrada", sa.String(length=4), nullable=True))
        batch_op.add_column(sa.Column("cst_icms", sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column("cst_pis", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("cst_cofins", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("cst_ibs_cbs", sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column("classificacao_tributaria", sa.String(length=6), nullable=True))

    with op.batch_alter_table("itens_nota_fiscal", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ncm", sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column("cfop", sa.String(length=4), nullable=True))
        batch_op.add_column(sa.Column("cst_icms", sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column("base_icms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("aliquota_icms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("valor_icms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("cst_pis", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("base_pis", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("aliquota_pis", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("valor_pis", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("cst_cofins", sa.String(length=2), nullable=True))
        batch_op.add_column(sa.Column("base_cofins", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("aliquota_cofins", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("valor_cofins", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("cst_ibs_cbs", sa.String(length=3), nullable=True))
        batch_op.add_column(sa.Column("classificacao_tributaria", sa.String(length=6), nullable=True))
        batch_op.add_column(sa.Column("base_ibs_cbs", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("aliquota_ibs", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("valor_ibs", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("aliquota_cbs", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("valor_cbs", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("itens_nota_fiscal", schema=None) as batch_op:
        batch_op.drop_column("valor_cbs")
        batch_op.drop_column("aliquota_cbs")
        batch_op.drop_column("valor_ibs")
        batch_op.drop_column("aliquota_ibs")
        batch_op.drop_column("base_ibs_cbs")
        batch_op.drop_column("classificacao_tributaria")
        batch_op.drop_column("cst_ibs_cbs")
        batch_op.drop_column("valor_cofins")
        batch_op.drop_column("aliquota_cofins")
        batch_op.drop_column("base_cofins")
        batch_op.drop_column("cst_cofins")
        batch_op.drop_column("valor_pis")
        batch_op.drop_column("aliquota_pis")
        batch_op.drop_column("base_pis")
        batch_op.drop_column("cst_pis")
        batch_op.drop_column("valor_icms")
        batch_op.drop_column("aliquota_icms")
        batch_op.drop_column("base_icms")
        batch_op.drop_column("cst_icms")
        batch_op.drop_column("cfop")
        batch_op.drop_column("ncm")

    with op.batch_alter_table("pecas", schema=None) as batch_op:
        batch_op.drop_column("classificacao_tributaria")
        batch_op.drop_column("cst_ibs_cbs")
        batch_op.drop_column("cst_cofins")
        batch_op.drop_column("cst_pis")
        batch_op.drop_column("cst_icms")
        batch_op.drop_column("cfop_entrada")
        batch_op.drop_column("ncm")
