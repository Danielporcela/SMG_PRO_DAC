"""Restauração do backup JSON gerado em Relatórios.

Regras de segurança adotadas:
- Só o administrador restaura.
- Usuários e senhas NÃO são tocados: quem tem acesso hoje continua tendo.
  O backup guarda a lista de usuários apenas para conferência.
- A restauração é total: os dados operacionais atuais são substituídos pelos
  do arquivo. Por isso a tela pede confirmação digitada.
- Tudo acontece em uma única transação: se qualquer registro falhar, nada é
  gravado e o banco continua como estava.
"""
from datetime import date

from extensions import db
from models import (Abastecimento, Fornecedor, ItemOS, Motorista, MovimentoEstoque,
                    Orcamento, OrdemServico, Peca, Pneu, Veiculo)
from services.crud import ErroNegocio

# ordem de exclusão: filhos antes dos pais
ORDEM_LIMPEZA = [ItemOS, MovimentoEstoque, Abastecimento, OrdemServico, Pneu,
                 Orcamento, Peca, Veiculo, Motorista, Fornecedor]

# (chave no arquivo, modelo, campos aceitos)
TABELAS = [
    ("fornecedores", Fornecedor,
     ["id", "nome", "tipo", "cnpj", "telefone", "cidade", "contato", "ativo"]),
    ("motoristas", Motorista,
     ["id", "nome", "matricula", "cnh", "categoria_cnh", "validade_cnh", "telefone",
      "setor", "ativo"]),
    ("veiculos", Veiculo,
     ["id", "prefixo", "placa", "marca", "modelo", "ano", "tipo", "combustivel",
      "centro_custo", "setor", "hodometro", "horimetro", "situacao",
      "km_ultima_troca_oleo", "intervalo_troca_oleo", "data_ultima_preventiva",
      "intervalo_preventiva_dias", "orcamento_mensal", "observacao", "ativo"]),
    ("pecas", Peca,
     ["id", "codigo", "descricao", "grupo", "unidade", "quantidade", "estoque_minimo",
      "custo_unitario", "localizacao", "fornecedor_id"]),
    ("ordens", OrdemServico,
     ["id", "numero", "data_abertura", "data_fechamento", "veiculo_id", "motorista_id",
      "fornecedor_id", "mecanico", "tipo", "prioridade", "status", "grupo",
      "km_veiculo", "descricao", "custo_mao_obra", "custo_servicos", "avaliacao"]),
    ("abastecimentos", Abastecimento,
     ["id", "data", "veiculo_id", "motorista_id", "fornecedor_id", "combustivel",
      "km_atual", "litros", "valor_litro", "valor_total", "tanque_cheio",
      "km_percorridos", "km_por_litro", "custo_por_km"]),
    ("pneus", Pneu,
     ["id", "numero_fogo", "veiculo_id", "posicao", "marca", "medida", "sulco_mm",
      "vida", "km_instalacao", "data_instalacao", "data_medicao", "status", "custo"]),
    ("orcamentos", Orcamento,
     ["id", "ano", "mes", "categoria", "veiculo_id", "centro_custo", "meta_valor"]),
    ("movimentos", MovimentoEstoque,
     ["id", "data", "peca_id", "tipo", "quantidade", "custo_unitario", "documento",
      "ordem_servico_id", "observacao"]),
]

CAMPOS_DATA = {"data", "data_abertura", "data_fechamento", "validade_cnh",
               "data_ultima_preventiva", "data_instalacao", "data_medicao"}

CAMPOS_ITEM = ["id", "ordem_servico_id", "peca_id", "descricao", "grupo", "quantidade",
               "valor_unitario", "tipo_item", "prestador_servico", "baixado_estoque"]


def _valor(campo, bruto):
    if campo in CAMPOS_DATA and bruto:
        return date.fromisoformat(str(bruto)[:10])
    return bruto


def _montar(Model, registro, campos):
    obj = Model()
    for campo in campos:
        if campo in registro:
            setattr(obj, campo, _valor(campo, registro[campo]))
    return obj


def restaurar(pacote):
    """Substitui os dados operacionais pelos do arquivo. Devolve o resumo."""
    if not isinstance(pacote, dict):
        raise ErroNegocio("O arquivo não é um backup do SGMF.")
    if not any(chave in pacote for chave, _, _ in TABELAS):
        raise ErroNegocio("O arquivo não parece um backup do SGMF: "
                          "nenhuma tabela conhecida foi encontrada.")

    resumo = {}
    try:
        for Model in ORDEM_LIMPEZA:
            Model.query.delete()
        db.session.flush()

        for chave, Model, campos in TABELAS:
            registros = pacote.get(chave) or []
            for registro in registros:
                db.session.add(_montar(Model, registro, campos))
            db.session.flush()
            resumo[chave] = len(registros)

        itens = 0
        for ordem in pacote.get("ordens") or []:
            for item in ordem.get("itens") or []:
                dados = dict(item)
                dados.setdefault("ordem_servico_id", ordem.get("id"))
                db.session.add(_montar(ItemOS, dados, CAMPOS_ITEM))
                itens += 1
        resumo["itens_os"] = itens

        db.session.commit()
    except ErroNegocio:
        db.session.rollback()
        raise
    except Exception as e:
        db.session.rollback()
        raise ErroNegocio(f"O arquivo tem dados inconsistentes e nada foi alterado "
                          f"({e.__class__.__name__}).")

    _corrigir_sequencias()
    return resumo


def _corrigir_sequencias():
    """No PostgreSQL, os contadores de id precisam pular os ids restaurados."""
    if not db.engine.dialect.name.startswith("postgres"):
        return
    from sqlalchemy import text
    for _, Model in [(c, m) for c, m, _ in TABELAS] + [("itens_os", ItemOS)]:
        tabela = Model.__tablename__
        db.session.execute(text(
            f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {tabela}), 1))"))
    db.session.commit()
