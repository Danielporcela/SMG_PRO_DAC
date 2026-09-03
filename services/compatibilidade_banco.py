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
            "fechado_por": "VARCHAR(120)",
            "data_fechamento": "DATE",
        },
        "itens_ordem_compra": {
            "ordem_compra_id": "INTEGER",
            "peca_id": "INTEGER",
            "descricao": "VARCHAR(160)",
            "unidade": "VARCHAR(10)",
            "quantidade": "FLOAT",
            "valor_unitario": "FLOAT",
            "observacao": "VARCHAR(200)",
            # Campos adicionados posteriormente ao módulo de compras.
            # Precisam ser garantidos aqui porque bancos antigos podem estar
            # marcados no Alembic como atualizados, mas ainda não possuir
            # essas colunas. Sem elas, o SELECT de ItemOrdemCompra falha
            # quando /api/ordens_compra carrega a lista da tela.
            "comprado": "BOOLEAN DEFAULT false",
            "comprado_por": "VARCHAR(120)",
            "data_compra_item": "DATE",
            "recebido": "BOOLEAN DEFAULT false",
            "data_recebimento": "DATE",
            "recebido_por": "VARCHAR(120)",
        },
    }

    with engine.begin() as conn:
        for tabela, colunas in esperadas.items():
            existentes = {c["name"] for c in inspect(engine).get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    conn.execute(text(f'ALTER TABLE "{tabela}" ADD COLUMN "{nome}" {tipo}'))

    # Corrige registros antigos que possam ter NULL no campo booleano.
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE itens_ordem_compra SET comprado = false "
            "WHERE comprado IS NULL"))

    # Instalações antigas tinham o fluxo Pendente/Aprovada/Reprovada/Comprada.
    # O fluxo atual é Compras do dia/Efetuado a compra/Fechada — converte o
    # que já estiver gravado para o status mais próximo, uma única vez.
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE ordens_compra SET status = 'Compras do dia' "
            "WHERE status IN ('Pendente', 'Aprovada', 'Reprovada')"))
        conn.execute(text(
            "UPDATE ordens_compra SET status = 'Efetuado a compra' "
            "WHERE status = 'Comprada'"))
        # Ordens antigas já compradas não têm itens marcados como recebidos —
        # sem essa marcação, todo item delas apareceria como pendência nova.
        # Como não há como saber o que já chegou, assume-se recebido para não
        # gerar uma lista de pendências cheia de itens de compras já feitas.
        conn.execute(text(
            "UPDATE itens_ordem_compra SET recebido = true "
            "WHERE COALESCE(recebido, false) != true AND ordem_compra_id IN ("
            "  SELECT id FROM ordens_compra WHERE status = 'Efetuado a compra')"))


def garantir_pecas_serial():
    """Garante a estrutura mínima do rastreio de peças por número de série.

    Cria as tabelas novas (pecas_serial, movimentos_peca_serial,
    itens_os_pecas_serial) e a coluna numeros_serie em itens_nota_fiscal,
    resolvendo instalações antigas do mesmo jeito que garantir_ordens_compra
    já faz para o módulo de compras.
    """
    from models import ItemOSPecaSerial, MovimentoPecaSerial, PecaSerial

    engine = db.engine
    insp = inspect(engine)
    tabelas = set(insp.get_table_names())

    if "pecas_serial" not in tabelas:
        PecaSerial.__table__.create(engine, checkfirst=True)
    if "movimentos_peca_serial" not in tabelas:
        MovimentoPecaSerial.__table__.create(engine, checkfirst=True)
    if "itens_os_pecas_serial" not in tabelas:
        ItemOSPecaSerial.__table__.create(engine, checkfirst=True)

    insp = inspect(engine)
    with engine.begin() as conn:
        existentes = {c["name"] for c in insp.get_columns("itens_nota_fiscal")}
        if "numeros_serie" not in existentes:
            conn.execute(text('ALTER TABLE "itens_nota_fiscal" ADD COLUMN "numeros_serie" TEXT'))


def garantir_itens_os_servicos_terceiros():
    """Adiciona, sem apagar dados, os campos usados por serviços de terceiros.

    Instalações antigas recebem as colunas automaticamente no primeiro start
    da aplicação, tanto em SQLite quanto em PostgreSQL.
    """
    engine = db.engine
    insp = inspect(engine)
    if "itens_os" not in set(insp.get_table_names()):
        return

    esperadas = {
        "tipo_item": "VARCHAR(24)",
        "prestador_servico": "VARCHAR(120)",
    }
    with engine.begin() as conn:
        existentes = {c["name"] for c in inspect(engine).get_columns("itens_os")}
        for nome, tipo in esperadas.items():
            if nome not in existentes:
                conn.execute(text(f'ALTER TABLE "itens_os" ADD COLUMN "{nome}" {tipo}'))

def garantir_servicos_terceiros_financeiros():
    """Cria a tabela dos lançamentos financeiros de serviços de terceiros.

    A OS é apenas uma referência opcional; a despesa é registrada pela própria
    data do lançamento. Em instalações novas, ``db.create_all`` cria a tabela.
    Em bancos já existentes, esta função adiciona a tabela sem alterar dados.
    """
    from models import ServicoTerceiro

    engine = db.engine
    insp = inspect(engine)
    tabelas = set(insp.get_table_names())

    # Em uma instalação totalmente nova, as tabelas-pai ainda serão criadas
    # por db.create_all logo depois. Evita criar FK antes das tabelas-pai.
    if "veiculos" not in tabelas or "ordens_servico" not in tabelas:
        return
    if "servicos_terceiros" not in tabelas:
        ServicoTerceiro.__table__.create(engine, checkfirst=True)

def garantir_lavagens_financeiro():
    """Cria a tabela dos lançamentos financeiros de lavagem.

    Em instalações novas, ``db.create_all`` cria a tabela. Em bancos já
    existentes, esta função adiciona a tabela sem alterar dados.
    """
    from models import Lavagem

    engine = db.engine
    insp = inspect(engine)
    tabelas = set(insp.get_table_names())

    if "veiculos" not in tabelas:
        return
    if "lavagens" not in tabelas:
        Lavagem.__table__.create(engine, checkfirst=True)

def garantir_usuario_movimentos_estoque():
    """Adiciona a identificação do responsável sem alterar registros existentes."""
    engine = db.engine
    insp = inspect(engine)
    if "movimentos_estoque" not in set(insp.get_table_names()):
        return

    esperadas = {
        "usuario_id": "INTEGER",
        "usuario_nome": "VARCHAR(120)",
    }
    with engine.begin() as conn:
        existentes = {c["name"] for c in inspect(engine).get_columns("movimentos_estoque")}
        for nome, tipo in esperadas.items():
            if nome not in existentes:
                conn.execute(text(f'ALTER TABLE "movimentos_estoque" ADD COLUMN "{nome}" {tipo}'))



def garantir_grupos_consumo():
    """Cria grupos de consumo e vínculos opcionais sem excluir dados existentes."""
    from models import GrupoConsumo

    engine = db.engine
    insp = inspect(engine)
    tabelas = set(insp.get_table_names())

    if "veiculos" not in tabelas:
        return
    if "grupos_consumo" not in tabelas:
        GrupoConsumo.__table__.create(engine, checkfirst=True)

    estruturas = {
        "veiculos": {"grupo_consumo_legado": "BOOLEAN DEFAULT FALSE"},
        "movimentos_estoque": {"grupo_consumo_id": "INTEGER"},
        "orcamentos": {"grupo_consumo_id": "INTEGER"},
    }
    with engine.begin() as conn:
        for tabela, colunas in estruturas.items():
            if tabela not in set(inspect(engine).get_table_names()):
                continue
            existentes = {c["name"] for c in inspect(engine).get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    conn.execute(text(f'ALTER TABLE "{tabela}" ADD COLUMN "{nome}" {tipo}'))

    from services.grupos_consumo import garantir_grupos_padrao, marcar_veiculos_grupo_consumo_legado
    garantir_grupos_padrao()
    marcar_veiculos_grupo_consumo_legado()
    db.session.commit()
