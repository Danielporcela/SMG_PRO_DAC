"""Compatibilidade de banco para módulos adicionados após a instalação inicial."""
from sqlalchemy import inspect, text

from extensions import db


def garantir_ordens_compra():
    """Garante a estrutura mínima do módulo de ordens de compra.

    Resolve instalações antigas em que o código do módulo foi publicado antes
    da atualização correspondente do banco de dados.
    """
    from models import ItemOrdemCompra, OrdemCompra

    engine = db.engine
    insp = inspect(engine)
    tabelas = set(insp.get_table_names())

    if "ordens_compra" not in tabelas:
        OrdemCompra.__table__.create(engine, checkfirst=True)
    if "itens_ordem_compra" not in tabelas:
        ItemOrdemCompra.__table__.create(engine, checkfirst=True)

    # Reinspeciona, pois alguma tabela pode ter acabado de ser criada.
    insp = inspect(engine)

    esperadas = {
        "ordens_compra": {
            "numero": "VARCHAR(20)",
            "data_solicitacao": "DATE",
            "solicitante": "VARCHAR(120)",
            "setor": "VARCHAR(60)",
            "fornecedor_id": "INTEGER",
            "prioridade": "VARCHAR(20)",
            "status": "VARCHAR(20)",
            "justificativa": "TEXT",
            "observacao": "VARCHAR(200)",
            "aprovado_por": "VARCHAR(120)",
            "data_aprovacao": "DATE",
            "motivo_reprovacao": "VARCHAR(200)",
            "comprado_por": "VARCHAR(120)",
            "data_compra": "DATE",
        },
        "itens_ordem_compra": {
            "ordem_compra_id": "INTEGER",
            "peca_id": "INTEGER",
            "descricao": "VARCHAR(160)",
            "unidade": "VARCHAR(10)",
            "quantidade": "FLOAT",
            "valor_unitario": "FLOAT",
            "observacao": "VARCHAR(200)",
        },
    }

    with engine.begin() as conn:
        for tabela, colunas in esperadas.items():
            existentes = {c["name"] for c in inspect(engine).get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    conn.execute(text(f'ALTER TABLE "{tabela}" ADD COLUMN "{nome}" {tipo}'))
