"""módulo de uniformes

Revision ID: e5b8d1f0a237
Revises: d8a3f6c2b104
Create Date: 2026-08-17 03:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5b8d1f0a237"
down_revision = "d8a3f6c2b104"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    tabelas = set(inspetor.get_table_names())

    if "funcionarios" not in tabelas:
        op.create_table(
            "funcionarios",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nome", sa.String(length=120), nullable=False),
            sa.Column("matricula", sa.String(length=30), nullable=True),
            sa.Column("cargo", sa.String(length=60), nullable=True),
            sa.Column("setor", sa.String(length=60), nullable=True),
            sa.Column("telefone", sa.String(length=20), nullable=True),
            sa.Column("ativo", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "itens_uniforme" not in tabelas:
        op.create_table(
            "itens_uniforme",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("codigo", sa.String(length=20), nullable=False),
            sa.Column("descricao", sa.String(length=80), nullable=False),
            sa.Column("unidade", sa.String(length=10), nullable=True),
            sa.Column("quantidade", sa.Float(), nullable=True),
            sa.Column("estoque_minimo", sa.Float(), nullable=True),
            sa.Column("ativo", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("codigo"),
        )
        with op.batch_alter_table("itens_uniforme", schema=None) as batch_op:
            batch_op.create_index(batch_op.f("ix_itens_uniforme_codigo"), ["codigo"], unique=True)

    tabelas = set(sa.inspect(bind).get_table_names())

    if "entregas_uniforme" not in tabelas:
        op.create_table(
            "entregas_uniforme",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("data", sa.Date(), nullable=True),
            sa.Column("funcionario_id", sa.Integer(), nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("tamanho", sa.String(length=10), nullable=True),
            sa.Column("tipo_entrega", sa.String(length=15), nullable=True),
            sa.Column("quantidade", sa.Float(), nullable=True),
            sa.Column("observacao", sa.String(length=200), nullable=True),
            sa.ForeignKeyConstraint(["funcionario_id"], ["funcionarios.id"]),
            sa.ForeignKeyConstraint(["item_id"], ["itens_uniforme.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    tabelas = set(sa.inspect(bind).get_table_names())

    if "movimentos_uniforme" not in tabelas:
        op.create_table(
            "movimentos_uniforme",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("data", sa.Date(), nullable=True),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("tipo", sa.String(length=10), nullable=True),
            sa.Column("quantidade", sa.Float(), nullable=True),
            sa.Column("documento", sa.String(length=60), nullable=True),
            sa.Column("entrega_id", sa.Integer(), nullable=True),
            sa.Column("observacao", sa.String(length=200), nullable=True),
            sa.ForeignKeyConstraint(["item_id"], ["itens_uniforme.id"]),
            sa.ForeignKeyConstraint(["entrega_id"], ["entregas_uniforme.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    op.drop_table("movimentos_uniforme")
    op.drop_table("entregas_uniforme")
    with op.batch_alter_table("itens_uniforme", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_itens_uniforme_codigo"))
    op.drop_table("itens_uniforme")
    op.drop_table("funcionarios")
