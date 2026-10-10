"""adiciona ultimo_acesso ao usuario (logins conectados agora no Painel)"""
from alembic import op
import sqlalchemy as sa

revision = "a2f7e6c1b930"
down_revision = ("c2d4e6f8a901", "f4a7b8c9d012")
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspetor = sa.inspect(bind)
    colunas = {c["name"] for c in inspetor.get_columns("usuarios")}
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        if "ultimo_acesso" not in colunas:
            batch_op.add_column(sa.Column("ultimo_acesso", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("usuarios", schema=None) as batch_op:
        batch_op.drop_column("ultimo_acesso")
