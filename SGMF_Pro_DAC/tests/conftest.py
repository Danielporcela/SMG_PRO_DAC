"""Configuração da suíte de testes.

Cada teste roda em um banco SQLite temporário, isolado do banco real.
"""
import os
import tempfile

import pytest

from app import criar_app
from config import Config
from extensions import db


class ConfigTeste(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "chave-de-teste"
    ADMIN_EMAIL = "admin@teste.local"


@pytest.fixture()
def app():
    """Banco limpo a cada teste.

    Por padrão usa um SQLite temporário. Para rodar a mesma suíte contra o
    PostgreSQL (o banco da produção), aponte TEST_DATABASE_URL:

        TEST_DATABASE_URL=postgresql://usuario:senha@localhost/sgmf_teste \
            python -m pytest tests -q
    """
    os.environ["ADMIN_EMAIL"] = "admin@teste.local"
    os.environ["ADMIN_SENHA"] = "teste123"

    url_externa = os.environ.get("TEST_DATABASE_URL")
    arquivo = None

    if url_externa:
        ConfigTeste.SQLALCHEMY_DATABASE_URI = url_externa
        _limpar_banco(url_externa)
    else:
        arquivo = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        arquivo.close()
        ConfigTeste.SQLALCHEMY_DATABASE_URI = f"sqlite:///{arquivo.name}"

    aplicacao = criar_app(ConfigTeste)
    yield aplicacao

    with aplicacao.app_context():
        db.session.remove()
        db.drop_all()
    if arquivo:
        os.unlink(arquivo.name)


def _limpar_banco(url):
    """Apaga tudo antes do teste — inclusive a marca de versão do Alembic."""
    from sqlalchemy import create_engine, text
    motor = create_engine(url)
    with motor.begin() as conexao:
        conexao.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conexao.execute(text("CREATE SCHEMA public"))
    motor.dispose()


@pytest.fixture()
def cliente(app):
    return app.test_client()


@pytest.fixture()
def logado(cliente):
    """Cliente já autenticado como administrador."""
    resposta = cliente.post("/login", json={"email": "admin@teste.local", "senha": "teste123"})
    assert resposta.status_code == 200
    return cliente


@pytest.fixture()
def base(logado):
    """Cadastros mínimos usados por vários testes."""
    veiculo = logado.post("/api/veiculos", json={
        "prefixo": "FR-001", "placa": "ABC1D23", "tipo": "Ônibus",
        "hodometro": 100000, "km_ultima_troca_oleo": 95000,
        "intervalo_troca_oleo": 10000, "orcamento_mensal": 5000}).get_json()
    motorista = logado.post("/api/motoristas", json={"nome": "João da Silva"}).get_json()
    oficina = logado.post("/api/fornecedores", json={"nome": "Oficina Central",
                                                     "tipo": "Oficina"}).get_json()
    peca = logado.post("/api/pecas", json={
        "codigo": "FIL-001", "descricao": "Filtro de óleo", "grupo": "Motor",
        "unidade": "UN", "custo_unitario": 50, "estoque_minimo": 5,
        "quantidade_inicial": 20}).get_json()
    return {"veiculo": veiculo, "motorista": motorista, "oficina": oficina, "peca": peca}
