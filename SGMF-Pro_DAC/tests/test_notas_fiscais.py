"""Testes do lançamento fiscal de peças em notas de entrada."""


def criar_fornecedor_e_peca(logado):
    fornecedor = logado.post("/api/fornecedores", json={"nome": "Fornecedor Fiscal"}).get_json()
    peca = logado.post("/api/pecas", json={
        "codigo": "PEC001",
        "descricao": "Peça fiscal de teste",
        "unidade": "UN",
        "custo_unitario": 100,
        "ncm": "87089990",
        "cfop_entrada": "1102",
        "cst_icms": "000",
        "cst_pis": "50",
        "cst_cofins": "50",
        "cst_ibs_cbs": "000",
        "classificacao_tributaria": "000001",
    }).get_json()
    return fornecedor, peca


def test_item_nf_usa_peca_cadastrada_e_calcula_tributos(logado):
    fornecedor, peca = criar_fornecedor_e_peca(logado)
    nota = logado.post("/api/notas-fiscais", json={
        "numero": "1001", "fornecedor_id": fornecedor["id"]
    }).get_json()

    resposta = logado.post(f"/api/notas-fiscais/{nota['id']}/itens", json={
        "peca_id": peca["id"],
        "quantidade": 2,
        "valor_unitario": 100,
        "aliquota_icms": 18,
        "aliquota_pis": 1.65,
        "aliquota_cofins": 7.6,
        "aliquota_ibs": 0.1,
        "aliquota_cbs": 0.9,
    })
    assert resposta.status_code == 201
    item = resposta.get_json()["itens"][0]
    assert item["peca_id"] == peca["id"]
    assert item["ncm"] == "87089990"
    assert item["cfop"] == "1102"
    assert item["cst_icms"] == "000"
    assert item["base_icms"] == 200
    assert item["valor_icms"] == 36
    assert item["valor_pis"] == 3.3
    assert item["valor_cofins"] == 15.2
    assert item["valor_ibs"] == 0.2
    assert item["valor_cbs"] == 1.8


def test_item_nf_pode_ser_editado_enquanto_nota_esta_aberta(logado):
    fornecedor, peca = criar_fornecedor_e_peca(logado)
    nota = logado.post("/api/notas-fiscais", json={
        "numero": "1002", "fornecedor_id": fornecedor["id"]
    }).get_json()
    criado = logado.post(f"/api/notas-fiscais/{nota['id']}/itens", json={
        "peca_id": peca["id"], "quantidade": 1, "valor_unitario": 100
    }).get_json()["itens"][0]

    resposta = logado.put(f"/api/notas-fiscais/{nota['id']}/itens/{criado['id']}", json={
        "peca_id": peca["id"],
        "quantidade": 3,
        "valor_unitario": 90,
        "base_icms": 270,
        "aliquota_icms": 12,
    })
    assert resposta.status_code == 200
    item = resposta.get_json()["itens"][0]
    assert item["quantidade"] == 3
    assert item["valor_total"] == 270
    assert item["valor_icms"] == 32.4


def test_finalizar_nf_atualiza_estoque(logado):
    fornecedor, peca = criar_fornecedor_e_peca(logado)
    nota = logado.post("/api/notas-fiscais", json={
        "numero": "1003", "fornecedor_id": fornecedor["id"]
    }).get_json()
    logado.post(f"/api/notas-fiscais/{nota['id']}/itens", json={
        "peca_id": peca["id"], "quantidade": 4, "valor_unitario": 100
    })
    resposta = logado.post(f"/api/notas-fiscais/{nota['id']}/finalizar", json={})
    assert resposta.status_code == 200
    atualizada = logado.get(f"/api/pecas/{peca['id']}").get_json()
    assert atualizada["quantidade"] == 4


def test_fluxo_cadastra_peca_durante_nota_e_finaliza(logado):
    fornecedor = logado.post("/api/fornecedores", json={"nome": "Fornecedor Cadastro Rápido"}).get_json()
    nota = logado.post("/api/notas-fiscais", json={
        "numero": "1004", "fornecedor_id": fornecedor["id"]
    }).get_json()

    peca = logado.post("/api/pecas", json={
        "codigo": "NOV001",
        "descricao": "Peça criada durante a nota",
        "unidade": "UN",
        "fornecedor_id": fornecedor["id"],
        "custo_unitario": 75,
        "ncm": "87089990",
        "cfop_entrada": "1102",
        "cst_icms": "000",
        "cst_pis": "50",
        "cst_cofins": "50",
    })
    assert peca.status_code == 201
    peca = peca.get_json()
    assert peca["fornecedor_id"] == fornecedor["id"]

    item = logado.post(f"/api/notas-fiscais/{nota['id']}/itens", json={
        "peca_id": peca["id"],
        "quantidade": 3,
        "valor_unitario": 75,
        "aliquota_icms": 18,
    })
    assert item.status_code == 201
    assert item.get_json()["qtd_itens"] == 1

    finalizada = logado.post(f"/api/notas-fiscais/{nota['id']}/finalizar", json={})
    assert finalizada.status_code == 200
    assert finalizada.get_json()["status"] == "Finalizada"
    atualizada = logado.get(f"/api/pecas/{peca['id']}").get_json()
    assert atualizada["quantidade"] == 3
