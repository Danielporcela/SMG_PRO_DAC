"""posição de pneu na ordem de serviço

Revision ID: b7f2c1d4e890
Revises: a1c3f0d9e2b4
Create Date: 2026-08-12 17:20:00
"""

from alembic import op
import sqlalchemy as sa

revision = "b7f2c1d4e890"
down_revision = "a1c3f0d9e2b4"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)

    colunas = {coluna["name"] for coluna in inspetor.get_columns("itens_os")}

    chaves = inspetor.get_foreign_keys("itens_os")
    possui_fk_pneu = any(
        fk.get("constrained_columns") == ["pneu_substituido_id"] for fk in chaves
    )

    with op.batch_alter_table("itens_os", schema=None) as batch_op:
        if "posicao_pneu" not in colunas:
            batch_op.add_column(
                sa.Column("posicao_pneu", sa.String(length=40), nullable=True)
            )

        if "pneu_substituido_id" not in colunas:
            batch_op.add_column(
                sa.Column("pneu_substituido_id", sa.Integer(), nullable=True)
            )

        if not possui_fk_pneu:
            batch_op.create_foreign_key(
                "fk_itens_os_pneu_substituido_id",
                "pneus",
                ["pneu_substituido_id"],
                ["id"],
            )


def downgrade():
    pass
