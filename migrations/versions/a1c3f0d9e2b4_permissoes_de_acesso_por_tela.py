"""permissões de acesso por tela

Revision ID: a1c3f0d9e2b4
Revises: 8d1cc15d1bb5
Create Date: 2026-08-08 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1c3f0d9e2b4'
down_revision = '8d1cc15d1bb5'
branch_labels = None
depends_on = None


def upgrade():
    # ### comandos gerados manualmente, no mesmo padrão do restante do projeto ###
    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cargo', sa.String(length=60), nullable=True))

    op.create_table(
        'permissoes_acesso',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('tela', sa.String(length=30), nullable=False),
        sa.Column('nivel', sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('usuario_id', 'tela', name='uq_permissao_usuario_tela'),
    )
    with op.batch_alter_table('permissoes_acesso', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_permissoes_acesso_usuario_id'),
                              ['usuario_id'], unique=False)
    # ### fim dos comandos ###


def downgrade():
    # ### comandos gerados manualmente ###
    with op.batch_alter_table('permissoes_acesso', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_permissoes_acesso_usuario_id'))
    op.drop_table('permissoes_acesso')

    with op.batch_alter_table('usuarios', schema=None) as batch_op:
        batch_op.drop_column('cargo')
    # ### fim dos comandos ###
