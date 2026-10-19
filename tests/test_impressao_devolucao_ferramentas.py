"""Impressão individual e exclusão lógica de ferramentas sob responsabilidade."""

SENHA_ADMIN = {"X-SGMF-Admin-Password": "teste123"}


def _cenario(logado):
    mecanismo = logado.post("/api/funcionarios", json={
        "nome": "Alice Mecânica", "cargo": "Mecânico", "ativo": True}).get_json()
    outro = logado.post("/api/funcionarios", json={
        "nome": "Bruno Mecânico", "cargo": "Mecânico", "ativo": True}).get_json()
    ferramenta = logado.post("/api/ferramentas", json={
        "codigo": "CH-080", "descricao": "Chave combinada 8mm", "custo_unitario": 80,
        "unidade": "UN", "quantidade_inicial": 8}).get_json()
    return mecanismo, outro, ferramenta


def _entregar(logado, funcionario, ferramenta, qtd=1):
    resultado = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": funcionario["id"], "ferramenta_id": ferramenta["id"],
        "quantidade": qtd})
    assert resultado.status_code == 201, resultado.get_json()
    return resultado.get_json()


def test_impressao_mostra_somente_ferramentas_do_mecanico(logado):
    mecanico, outro, ferramenta = _cenario(logado)
    _entregar(logado, mecanico, ferramenta, 2)
    _entregar(logado, outro, ferramenta, 1)
    resposta = logado.get(f"/api/entregas_ferramenta/imprimir/{mecanico['id']}")
    assert resposta.status_code == 200
    pagina = resposta.get_data(as_text=True)
    assert "Alice Mecânica" in pagina
    assert "Bruno Mecânico" not in pagina
    assert "CH-080" in pagina and "Chave combinada 8mm" in pagina
    assert "Total de unidades em posse: 2" in pagina
    assert resposta.headers.get("Cache-Control") == "no-store"


def test_impressao_sem_ferramentas_informa_vazio(logado):
    mecanico, _, _ = _cenario(logado)
    resposta = logado.get(f"/api/entregas_ferramenta/imprimir/{mecanico['id']}")
    assert resposta.status_code == 200
    assert "Nenhuma ferramenta em posse deste mecânico" in resposta.get_data(as_text=True)


def test_impressao_nao_autorizada_e_mecanico_inexistente(logado, cliente):
    mecanico, _, _ = _cenario(logado)
    assert logado.get('/api/entregas_ferramenta/imprimir/999999').status_code == 404
    cliente.get('/logout')
    assert cliente.get(f"/api/entregas_ferramenta/imprimir/{mecanico['id']}").status_code == 401


def test_excluir_do_mecanico_retorna_estoque_e_preserva_historico(logado):
    mecanico, _, ferramenta = _cenario(logado)
    entrega = _entregar(logado, mecanico, ferramenta, 3)
    antes = logado.get(f"/api/ferramentas/{ferramenta['id']}").get_json()["quantidade"]
    assert antes == 5
    resposta = logado.delete(f"/api/entregas_ferramenta/{entrega['id']}", headers=SENHA_ADMIN)
    assert resposta.status_code == 200
    assert logado.get('/api/entregas_ferramenta').get_json() == []
    atualizado = logado.get(f"/api/ferramentas/{ferramenta['id']}").get_json()["quantidade"]
    assert atualizado == 8
    historico = logado.get('/api/entregas_ferramenta?incluir_devolvidas=1').get_json()
    assert len(historico) == 1
    assert historico[0]['id'] == entrega['id']
    assert historico[0]['situacao'] == 'Devolvida'
    assert historico[0]['data_devolucao']
    assert historico[0]['devolvido_por']
    relatorio = logado.get(f"/api/entregas_ferramenta/imprimir/{mecanico['id']}")
    assert "Nenhuma ferramenta em posse" in relatorio.get_data(as_text=True)


def test_exclusao_repetida_nao_soma_estoque_duas_vezes(logado):
    mecanico, _, ferramenta = _cenario(logado)
    entrega = _entregar(logado, mecanico, ferramenta, 2)
    caminho = f"/api/entregas_ferramenta/{entrega['id']}"
    assert logado.delete(caminho, headers=SENHA_ADMIN).status_code == 200
    assert logado.delete(caminho, headers=SENHA_ADMIN).status_code == 400
    assert logado.get(f"/api/ferramentas/{ferramenta['id']}").get_json()["quantidade"] == 8


def test_exclusao_requer_senha_de_administrador(logado):
    mecanico, _, ferramenta = _cenario(logado)
    entrega = _entregar(logado, mecanico, ferramenta, 2)
    caminho = f"/api/entregas_ferramenta/{entrega['id']}"
    assert logado.delete(caminho).status_code == 403
    assert logado.get(f"/api/ferramentas/{ferramenta['id']}").get_json()["quantidade"] == 6


