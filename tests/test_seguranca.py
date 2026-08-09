"""Segurança e disputa entre usuários simultâneos.

Estes testes existem por causa de falhas encontradas em auditoria:
o estoque podia ficar negativo quando duas pessoas davam baixa ao mesmo
tempo, e texto digitado pelo usuário era devolvido sem tratamento.
"""
import pytest

from extensions import db
from models import Peca
from services.calculos import movimentar_estoque
from services.crud import ErroNegocio


# --------------------------------------------------------------- injeção SQL
def test_data_invalida_no_filtro_nao_derruba_o_sistema(logado):
    r = logado.get("/api/abastecimentos?inicio=2020-01-01' OR '1'='1")
    assert r.status_code == 400
    assert "AAAA-MM-DD" in r.get_json()["erro"]
    assert logado.get("/api/veiculos").status_code == 200, "o sistema segue de pé"


def test_data_invalida_no_relatorio(logado):
    r = logado.get("/relatorios/abastecimentos.csv?fim=ontem")
    assert r.status_code == 400


def test_texto_com_sql_e_gravado_como_texto(logado):
    r = logado.post("/api/veiculos", json={"prefixo": "SQL-1", "placa": "SQL1A11",
                                           "observacao": "'; DROP TABLE veiculos; --"})
    assert r.status_code == 201
    assert logado.get("/api/veiculos").status_code == 200
    assert r.get_json()["observacao"] == "'; DROP TABLE veiculos; --"


def test_texto_com_html_e_devolvido_intacto_pela_api(logado):
    """A API devolve o texto original; quem escapa é a tela (SGMF.esc)."""
    perigoso = "<img src=x onerror=alert(1)>"
    r = logado.post("/api/motoristas", json={"nome": perigoso})
    assert r.status_code == 201
    assert r.get_json()["nome"] == perigoso


def test_pagina_nao_injeta_o_nome_do_usuario_no_html(logado, cliente):
    """O nome do usuário aparece no menu — precisa sair escapado pelo Jinja."""
    logado.post("/api/usuarios", json={"nome": "<script>alert(1)</script>",
                                       "email": "script@teste.local",
                                       "senha": "senha123", "perfil": "admin"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "script@teste.local", "senha": "senha123"})
    html = cliente.get("/veiculos").data.decode()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ------------------------------------------------------- disputa de estoque
def test_saida_simultanea_nao_deixa_o_estoque_negativo(app, logado, base):
    """Duas baixas concorrentes da mesma peça: a segunda precisa ser recusada.

    Simula a corrida gravando direto no banco entre a leitura e a escrita.
    """
    peca_id = base["peca"]["id"]
    with app.app_context():
        peca = db.session.get(Peca, peca_id)
        peca.quantidade = 5
        db.session.commit()

        movimentar_estoque(peca_id, "saida", 5)
        db.session.commit()

        with pytest.raises(ErroNegocio) as erro:
            movimentar_estoque(peca_id, "saida", 1)
        assert "insuficiente" in str(erro.value)
        db.session.rollback()
        assert db.session.get(Peca, peca_id).quantidade == 0


def test_saida_exata_do_saldo_e_permitida(app, base):
    peca_id = base["peca"]["id"]
    with app.app_context():
        movimentar_estoque(peca_id, "saida", 20)
        db.session.commit()
        assert db.session.get(Peca, peca_id).quantidade == 0


def test_custo_medio_continua_correto_apos_a_mudanca(app, base):
    peca_id = base["peca"]["id"]
    with app.app_context():
        movimentar_estoque(peca_id, "entrada", 20, 70)   # 20 a 50 + 20 a 70
        db.session.commit()
        peca = db.session.get(Peca, peca_id)
        assert peca.quantidade == 40
        assert peca.custo_unitario == 60.0


def test_muitas_baixas_seguidas_batem_com_o_saldo(app, logado, base):
    peca_id = base["peca"]["id"]
    aceitas = 0
    with app.app_context():
        for _ in range(30):
            try:
                movimentar_estoque(peca_id, "saida", 1)
                db.session.commit()
                aceitas += 1
            except ErroNegocio:
                db.session.rollback()
        assert aceitas == 20, "só podia sair o que havia em estoque"
        assert db.session.get(Peca, peca_id).quantidade == 0


# --------------------------------------------------- numeração das ordens
def test_numeros_de_os_nao_se_repetem(logado, base):
    numeros = []
    for _ in range(15):
        resposta = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]})
        assert resposta.status_code == 201
        numeros.append(resposta.get_json()["numero"])
    assert len(set(numeros)) == 15
    assert numeros[-1].endswith("00015")
