"""Cadastros: veículos, motoristas, oficinas e usuários."""


def test_cadastro_de_veiculo(logado):
    r = logado.post("/api/veiculos", json={"prefixo": "FR-010", "placa": "xyz1a11",
                                           "hodometro": 50000})
    assert r.status_code == 201
    dados = r.get_json()
    assert dados["placa"] == "XYZ1A11", "a placa deve ser gravada em maiúsculas"
    assert dados["identificacao"] == "FR-010 · XYZ1A11"


def test_veiculo_exige_prefixo_e_placa(logado):
    r = logado.post("/api/veiculos", json={"marca": "Volvo"})
    assert r.status_code == 400
    assert "prefixo" in r.get_json()["erro"]


def test_placa_duplicada_e_recusada(logado, base):
    r = logado.post("/api/veiculos", json={"prefixo": "FR-999", "placa": "ABC1D23"})
    assert r.status_code == 400
    assert "duplicad" in r.get_json()["erro"]


def test_proxima_troca_de_oleo_calculada(logado, base):
    veiculo = logado.get(f"/api/veiculos/{base['veiculo']['id']}").get_json()
    assert veiculo["km_proxima_troca_oleo"] == 105000


def test_edicao_e_exclusao_de_veiculo(logado, base):
    vid = base["veiculo"]["id"]
    r = logado.put(f"/api/veiculos/{vid}", json={"setor": "Transporte escolar",
                                                 "hodometro": 101000})
    assert r.status_code == 200
    assert r.get_json()["setor"] == "Transporte escolar"
    assert logado.delete(f"/api/veiculos/{vid}").status_code == 200
    assert logado.get(f"/api/veiculos/{vid}").status_code == 404


def test_veiculo_com_lancamento_nao_pode_ser_excluido(logado, base):
    logado.post("/api/abastecimentos", json={"veiculo_id": base["veiculo"]["id"],
                                             "km_atual": 100500, "litros": 60,
                                             "valor_litro": 6})
    r = logado.delete(f"/api/veiculos/{base['veiculo']['id']}")
    assert r.status_code == 400
    assert "vinculado" in r.get_json()["erro"]


def test_cadastro_de_motorista_com_data(logado):
    r = logado.post("/api/motoristas", json={"nome": "Maria Souza", "categoria_cnh": "D",
                                             "validade_cnh": "2027-03-15"})
    assert r.status_code == 201
    assert r.get_json()["validade_cnh"] == "2027-03-15"


def test_motorista_exige_nome(logado):
    assert logado.post("/api/motoristas", json={"cnh": "123"}).status_code == 400


def test_cadastro_de_fornecedor(logado):
    r = logado.post("/api/fornecedores", json={"nome": "Posto Ipiranga", "tipo": "Posto"})
    assert r.status_code == 201
    assert r.get_json()["identificacao"] == "Posto Ipiranga (Posto)"


def test_listagem_ordenada(logado):
    for nome in ["Zeus Auto Peças", "Alfa Mecânica", "Meio Termo"]:
        logado.post("/api/fornecedores", json={"nome": nome})
    nomes = [f["nome"] for f in logado.get("/api/fornecedores").get_json()]
    assert nomes == sorted(nomes)


def test_valor_invalido_em_campo_numerico(logado):
    r = logado.post("/api/veiculos", json={"prefixo": "FR-020", "placa": "QWE1R22",
                                           "hodometro": "muito longe"})
    assert r.status_code == 400
    assert "hodometro" in r.get_json()["erro"]


def test_senha_padrao_de_usuario_novo(logado, cliente):
    logado.post("/api/usuarios", json={"nome": "Sem senha", "email": "sem@teste.local"})
    logado.get("/logout")
    r = cliente.post("/login", json={"email": "sem@teste.local", "senha": "sgmf@123"})
    assert r.status_code == 200
