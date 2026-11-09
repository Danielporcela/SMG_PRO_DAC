"""Cadastro de serviços executados (ex.: Conserto de soldador) usado na tela
de Serviços de terceiros."""
SENHA_ADMIN = {"X-SGMF-Admin-Password": "teste123"}


def test_cadastrar_listar_e_excluir_servico_executado(logado):
    r = logado.post("/api/servicos-executados", json={"nome": "  Conserto   de soldador ", "ativo": True})
    assert r.status_code == 201, r.get_json()
    criado = r.get_json()
    assert criado["nome"] == "Conserto de soldador"      # espaços normalizados

    lista = logado.get("/api/servicos-executados").get_json()
    assert [s["nome"] for s in lista] == ["Conserto de soldador"]

    r = logado.delete(f"/api/servicos-executados/{criado['id']}", headers=SENHA_ADMIN)
    assert r.status_code == 200
    assert logado.get("/api/servicos-executados").get_json() == []


def test_nao_permite_servico_duplicado_nem_vazio(logado):
    assert logado.post("/api/servicos-executados", json={"nome": "Solda"}).status_code == 201
    r = logado.post("/api/servicos-executados", json={"nome": "SOLDA"})
    assert r.status_code == 400 and "já está cadastrado" in r.get_json()["erro"]
    assert logado.post("/api/servicos-executados", json={"nome": "   "}).status_code == 400


def test_pagina_tem_botao_de_cadastro(logado):
    html = logado.get("/servicos-terceiros").get_data(as_text=True)
    assert 'id="botaoCadastrarServico"' in html
    assert "Cadastrar serviço executado" in html
