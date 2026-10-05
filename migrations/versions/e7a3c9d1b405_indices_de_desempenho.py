"""indices de desempenho para o painel

Revision ID: e7a3c9d1b405
Revises: d09ef6a77750
Create Date: 2026-10-04 16:00:00.000000

Cria índices nas colunas usadas pelos filtros por período do painel.
É idempotente: só cria o índice que ainda não existir (bancos novos criados
por create_all já podem tê-los).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7a3c9d1b405'
down_revision = 'd09ef6a77750'
branch_labels = None
depends_on = None


INDICES = [
    ("ix_ordens_servico_data_abertura", "ordens_servico", ["data_abertura"]),
    ("ix_ordens_servico_veiculo_id", "ordens_servico", ["veiculo_id"]),
    ("ix_ordens_servico_veiculo_data", "ordens_servico", ["veiculo_id", "data_abertura"]),
    ("ix_ordens_servico_status", "ordens_servico", ["status"]),
    ("ix_itens_os_ordem_servico_id", "itens_os", ["ordem_servico_id"]),
    ("ix_abastecimentos_veiculo_data", "abastecimentos", ["veiculo_id", "data"]),
]


def _existentes(inspetor, tabela):
    try:
        return {i["name"] for i in inspetor.get_indexes(tabela)}
    except Exception:
        return set()


def upgrade():
    inspetor = sa.inspect(op.get_bind())
    tabelas = set(inspetor.get_table_names())
    for nome, tabela, colunas in INDICES:
        if tabela not in tabelas or nome in _existentes(inspetor, tabela):
            continue
        op.create_index(nome, tabela, colunas)


def downgrade():
    inspetor = sa.inspect(op.get_bind())
    tabelas = set(inspetor.get_table_names())
    for nome, tabela, _ in INDICES:
        if tabela in tabelas and nome in _existentes(inspetor, tabela):
            op.drop_index(nome, table_name=tabela)
