"""Acesso ao sistema: login, sessão, permissões e páginas."""
import pytest

PAGINAS = ["/", "/alertas", "/veiculos", "/motoristas", "/fornecedores", "/manutencao",
           "/combustivel", "/pneus", "/estoque", "/orcamento", "/ranking",
           "/relatorios", "/usuarios"]


def test_login_com_senha_correta(cliente):
    r = cliente.post("/login", json={"email": "admin@teste.local", "senha": "teste123"})
    assert r.status_code == 200
    assert r.get_json()["usuario"]["perfil"] == "admin"


def test_login_com_senha_errada(cliente):
    r = cliente.post("/login", json={"email": "admin@teste.local", "senha": "errada"})
    assert r.status_code == 401
    assert "não conferem" in r.get_json()["erro"]


def test_login_com_email_inexistente(cliente):
    r = cliente.post("/login", json={"email": "ninguem@teste.local", "senha": "x"})
    assert r.status_code == 401


def test_api_exige_sessao(cliente):
    r = cliente.get("/api/veiculos")
    assert r.status_code == 401


def test_pagina_sem_sessao_redireciona_para_login(cliente):
    r = cliente.get("/veiculos")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


@pytest.mark.parametrize("rota", PAGINAS)
def test_paginas_abrem_para_usuario_logado(logado, rota):
    r = logado.get(rota)
    assert r.status_code == 200
    assert b"SGMF" in r.data


def test_logout_encerra_sessao(logado):
    logado.get("/logout")
    assert logado.get("/api/veiculos").status_code == 401


def test_troca_de_senha(logado):
    assert logado.post("/api/trocar-senha",
                       json={"atual": "errada", "nova": "novasenha"}).status_code == 400
    assert logado.post("/api/trocar-senha",
                       json={"atual": "teste123", "nova": "123"}).status_code == 400
    assert logado.post("/api/trocar-senha",
                       json={"atual": "teste123", "nova": "novasenha1"}).status_code == 200
    logado.get("/logout")
    assert logado.post("/login", json={"email": "admin@teste.local",
                                       "senha": "novasenha1"}).status_code == 200


def test_operador_nao_gerencia_usuarios(logado, cliente):
    logado.post("/api/usuarios", json={"nome": "Operador", "email": "op@teste.local",
                                       "perfil": "operador", "senha": "operador123"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "op@teste.local", "senha": "operador123"})
    assert cliente.get("/api/usuarios").status_code == 403
    assert cliente.get("/api/veiculos").status_code == 200


def test_usuario_desativado_nao_entra(logado, cliente):
    criado = logado.post("/api/usuarios", json={"nome": "Bloqueado", "email": "bl@teste.local",
                                                "senha": "senha123", "ativo": True}).get_json()
    logado.put(f"/api/usuarios/{criado['id']}", json={"ativo": False})
    logado.get("/logout")
    r = cliente.post("/login", json={"email": "bl@teste.local", "senha": "senha123"})
    assert r.status_code == 403


def test_health_check(cliente):
    assert cliente.get("/saude").get_json()["status"] == "ok"


def test_pagina_inexistente(logado):
    assert logado.get("/pagina-que-nao-existe").status_code == 404
    assert logado.get("/api/rota-inexistente").status_code == 404
