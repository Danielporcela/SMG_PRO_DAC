"""libera finalização de OS para usuários do Almoxarifado

Revision ID: f4a7b8c9d012
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = "f4a7b8c9d012"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    usuarios = sa.table(
        "usuarios",
        sa.column("id", sa.Integer),
        sa.column("cargo", sa.String),
    )
    permissoes = sa.table(
        "permissoes_acesso",
        sa.column("id", sa.Integer),
        sa.column("usuario_id", sa.Integer),
        sa.column("tela", sa.String),
        sa.column("nivel", sa.String),
    )

    ids = [r[0] for r in bind.execute(
        sa.select(usuarios.c.id).where(
            sa.func.lower(sa.func.trim(usuarios.c.cargo)) == "almoxarifado"
        )
    ).fetchall()]

    for usuario_id in ids:
        existente = bind.execute(
            sa.select(permissoes.c.id).where(
                permissoes.c.usuario_id == usuario_id,
                permissoes.c.tela == "manutencao",
            )
        ).fetchone()
        if existente:
            bind.execute(
                sa.update(permissoes)
                .where(permissoes.c.id == existente[0])
                .values(nivel="editar")
            )
        else:
            bind.execute(
                sa.insert(permissoes).values(
                    usuario_id=usuario_id, tela="manutencao", nivel="editar"
                )
            )


def downgrade():
    bind = op.get_bind()
    permissoes = sa.table(
        "permissoes_acesso",
        sa.column("usuario_id", sa.Integer),
        sa.column("tela", sa.String),
        sa.column("nivel", sa.String),
    )
    usuarios = sa.table(
        "usuarios",
        sa.column("id", sa.Integer),
        sa.column("cargo", sa.String),
    )
    ids = sa.select(usuarios.c.id).where(
        sa.func.lower(sa.func.trim(usuarios.c.cargo)) == "almoxarifado"
    )
    bind.execute(
        sa.update(permissoes)
        .where(permissoes.c.usuario_id.in_(ids), permissoes.c.tela == "manutencao")
        .values(nivel="visualizar")
    )
