"""notas fiscais de entrada de peças

Revision ID: b7f2a4c9e1d3
Revises: a1c3f0d9e2b4
Create Date: 2026-08-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7f2a4c9e1d3'
down_revision = 'a1c3f0d9e2b4'
branch_labels = None
depends_on = None


def upgrade():
    # ### comandos gerados manualmente, no mesmo padrão do restante do projeto ###
    op.create_table(
        'notas_fiscais',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('numero', sa.String(length=30), nullable=False),
        sa.Column('serie', sa.String(length=10), nullable=True),
        sa.Column('data_emissao', sa.Date(), nullable=True),
        sa.Column('data_entrada', sa.Date(), nullable=True),
        sa.Column('fornecedor_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('observacao', sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(['fornecedor_id'], ['fornecedores.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('notas_fiscais', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notas_fiscais_numero'), ['numero'], unique=False)

    op.create_table(
        'itens_nota_fiscal',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nota_fiscal_id', sa.Integer(), nullable=False),
        sa.Column('peca_id', sa.Integer(), nullable=False),
        sa.Column('descricao', sa.String(length=160), nullable=True),
        sa.Column('quantidade', sa.Float(), nullable=True),
        sa.Column('valor_unitario', sa.Float(), nullable=True),
        sa.Column('baixado_estoque', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['nota_fiscal_id'], ['notas_fiscais.id'], ),
        sa.ForeignKeyConstraint(['peca_id'], ['pecas.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    # ### fim dos comandos ###


def downgrade():
    # ### comandos gerados manualmente ###
    op.drop_table('itens_nota_fiscal')

    with op.batch_alter_table('notas_fiscais', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notas_fiscais_numero'))
    op.drop_table('notas_fiscais')
    # ### fim dos comandos ###
