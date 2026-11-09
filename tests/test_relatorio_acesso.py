"""Relatório de acesso: cada login gera um registro consultável por data."""
from datetime import date


def test_login_gera_registro_e_relatorio_por_data(cliente):
    for _ in range(2):
        r = cliente.post("/login", json={"email": "admin@teste.local", "senha": "teste123"})
        assert r.status_code == 200
        cliente.get("/logout")
    cliente.post("/login", json={"email": "admin@teste.local", "senha": "errada"})  # falha: não conta
    cliente.post("/login", json={"email": "admin@teste.local", "senha": "teste123"})

    r = cliente.get(f"/api/relatorio-acesso?data={date.today().isoformat()}")
    assert r.status_code == 200
    dados = r.get_json()
    assert dados["total_acessos"] == 3
    assert dados["total_usuarios"] == 1
    assert dados["resumo"][0]["quantidade"] == 3
    assert len(dados["acessos"]) == 3 and dados["acessos"][0]["horario"]


def test_data_sem_acessos_vem_vazia(logado):
    dados = logado.get("/api/relatorio-acesso?data=2000-01-01").get_json()
    assert dados["total_acessos"] == 0 and dados["resumo"] == []


def test_pagina_e_api_somente_admin(cliente):
    assert cliente.get("/api/relatorio-acesso").status_code == 401
    r = cliente.post("/login", json={"email": "admin@teste.local", "senha": "teste123"})
    assert cliente.get("/relatorio-acesso").status_code == 200
