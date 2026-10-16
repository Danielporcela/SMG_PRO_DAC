"""Ferramentas dos mecânicos: a nota fiscal dá entrada no estoque e a
ferramenta colocada em nome do mecânico dá baixa."""
import pytest

SENHA_ADMIN = {"X-SGMF-Admin-Password": "teste123"}


@pytest.fixture()
def cenario(logado):
    """Fornecedor, mecânico, não-mecânico e uma ferramenta sem saldo."""
    fornecedor = logado.post("/api/fornecedores", json={
        "nome": "Casa das Ferramentas", "tipo": "Fornecedor"}).get_json()
    mecanico = logado.post("/api/funcionarios", json={
        "nome": "Carlos Mecânico", "cargo": "Mecânico", "ativo": True}).get_json()
    motorista = logado.post("/api/funcionarios", json={
        "nome": "Paulo Motorista", "cargo": "Motorista", "ativo": True}).get_json()
    ferramenta = logado.post("/api/ferramentas", json={
        "descricao": "Chave de impacto 1/2", "marca": "Bosch", "unidade": "UN",
        "custo_unitario": 100, "estoque_minimo": 2, "ativo": True}).get_json()
    return {"fornecedor": fornecedor, "mecanico": mecanico,
            "motorista": motorista, "ferramenta": ferramenta}


def _saldo(cliente, ferramenta_id):
    return cliente.get(f"/api/ferramentas/{ferramenta_id}").get_json()["quantidade"]


def _dar_entrada_por_nota(cliente, c, quantidade, valor=100, numero="1001"):
    """Lança a NF no padrão: cria a nota, lança o item e finaliza."""
    nota = cliente.post("/api/notas_fiscais_ferramenta", json={
        "numero": numero, "fornecedor_id": c["fornecedor"]["id"]})
    assert nota.status_code == 201, nota.get_json()
    nota_id = nota.get_json()["id"]
    item = cliente.post(f"/api/notas_fiscais_ferramenta/{nota_id}/itens", json={
        "ferramenta_id": c["ferramenta"]["id"], "quantidade": quantidade,
        "valor_unitario": valor})
    assert item.status_code == 201, item.get_json()
    return nota_id


# ------------------------------------------------------------- cadastro
def test_codigo_da_ferramenta_e_gerado_e_comeca_sem_saldo(logado, cenario):
    f = cenario["ferramenta"]
    assert f["codigo"] == "0001"
    assert f["quantidade"] == 0
    segunda = logado.post("/api/ferramentas", json={"descricao": "Torquímetro"}).get_json()
    assert segunda["codigo"] == "0002"


def test_saldo_inicial_entra_como_movimento(logado):
    f = logado.post("/api/ferramentas", json={
        "descricao": "Macaco hidráulico", "quantidade_inicial": 3,
        "custo_unitario": 250}).get_json()
    assert f["quantidade"] == 3
    movs = logado.get(f"/api/ferramentas/movimentos?ferramenta_id={f['id']}").get_json()
    assert len(movs) == 1 and movs[0]["tipo"] == "entrada"
    assert movs[0]["documento"] == "Saldo inicial"


def test_cadastro_nao_altera_saldo_na_edicao(logado, cenario):
    c = cenario
    nota_id = _dar_entrada_por_nota(logado, c, 5)
    logado.post(f"/api/notas_fiscais_ferramenta/{nota_id}/finalizar", json={})
    r = logado.put(f"/api/ferramentas/{c['ferramenta']['id']}", json={
        "descricao": "Chave de impacto", "quantidade": 999})
    assert r.status_code == 200
    assert _saldo(logado, c["ferramenta"]["id"]) == 5, "saldo só muda por movimento"


# ------------------------------------------------------- nota fiscal (entrada)
def test_nota_aberta_nao_mexe_no_estoque(logado, cenario):
    c = cenario
    _dar_entrada_por_nota(logado, c, 4)
    assert _saldo(logado, c["ferramenta"]["id"]) == 0


def test_finalizar_nota_da_entrada_no_estoque(logado, cenario):
    c = cenario
    nota_id = _dar_entrada_por_nota(logado, c, 4, valor=120)
    r = logado.post(f"/api/notas_fiscais_ferramenta/{nota_id}/finalizar", json={})
    assert r.status_code == 200
    nota = r.get_json()
    assert nota["status"] == "Finalizada" and nota["valor_total"] == 480
    assert all(i["baixado_estoque"] for i in nota["itens"])

    f = logado.get(f"/api/ferramentas/{c['ferramenta']['id']}").get_json()
    assert f["quantidade"] == 4
    assert f["custo_unitario"] == 120
    movs = logado.get(f"/api/ferramentas/movimentos?ferramenta_id={f['id']}").get_json()
    assert movs[0]["tipo"] == "entrada" and movs[0]["documento"] == "NF 1001"


def test_nota_finalizada_nao_aceita_mais_itens_nem_nova_finalizacao(logado, cenario):
    c = cenario
    nota_id = _dar_entrada_por_nota(logado, c, 2)
    logado.post(f"/api/notas_fiscais_ferramenta/{nota_id}/finalizar", json={})
    r = logado.post(f"/api/notas_fiscais_ferramenta/{nota_id}/itens", json={
        "ferramenta_id": c["ferramenta"]["id"], "quantidade": 1})
    assert r.status_code == 400
    assert logado.post(f"/api/notas_fiscais_ferramenta/{nota_id}/finalizar",
                       json={}).status_code == 400
    assert _saldo(logado, c["ferramenta"]["id"]) == 2, "não pode dar entrada duas vezes"


def test_nota_sem_itens_nao_finaliza(logado, cenario):
    nota = logado.post("/api/notas_fiscais_ferramenta", json={
        "numero": "55", "fornecedor_id": cenario["fornecedor"]["id"]}).get_json()
    r = logado.post(f"/api/notas_fiscais_ferramenta/{nota['id']}/finalizar", json={})
    assert r.status_code == 400


def test_uma_nota_aberta_por_fornecedor(logado, cenario):
    c = cenario
    _dar_entrada_por_nota(logado, c, 1, numero="1")
    r = logado.post("/api/notas_fiscais_ferramenta", json={
        "numero": "2", "fornecedor_id": c["fornecedor"]["id"]})
    assert r.status_code == 400 and "aberta" in r.get_json()["erro"]


def test_remover_item_e_excluir_nota_aberta(logado, cenario):
    c = cenario
    nota_id = _dar_entrada_por_nota(logado, c, 3)
    nota = logado.get(f"/api/notas_fiscais_ferramenta/{nota_id}").get_json()
    item_id = nota["itens"][0]["id"]
    r = logado.delete(f"/api/notas_fiscais_ferramenta/{nota_id}/itens/{item_id}",
                      headers=SENHA_ADMIN)
    assert r.status_code == 200 and r.get_json()["itens"] == []
    assert logado.delete(f"/api/notas_fiscais_ferramenta/{nota_id}",
                         headers=SENHA_ADMIN).status_code == 200


def test_item_com_quantidade_invalida_e_recusado(logado, cenario):
    c = cenario
    nota = logado.post("/api/notas_fiscais_ferramenta", json={
        "numero": "9", "fornecedor_id": c["fornecedor"]["id"]}).get_json()
    for qtd in (0, -2):
        r = logado.post(f"/api/notas_fiscais_ferramenta/{nota['id']}/itens", json={
            "ferramenta_id": c["ferramenta"]["id"], "quantidade": qtd})
        assert r.status_code == 400


# ------------------------------------------ ferramenta em nome do mecânico (baixa)
def _abastecer(logado, c, quantidade):
    nota_id = _dar_entrada_por_nota(logado, c, quantidade)
    logado.post(f"/api/notas_fiscais_ferramenta/{nota_id}/finalizar", json={})


def test_entrega_ao_mecanico_da_baixa_no_estoque(logado, cenario):
    c = cenario
    _abastecer(logado, c, 5)
    r = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["mecanico"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 2, "observacao": "Ferramenta nova"})
    assert r.status_code == 201, r.get_json()
    entrega = r.get_json()
    assert entrega["mecanico_nome"] == "Carlos Mecânico"
    assert entrega["valor_total"] == 200

    assert _saldo(logado, c["ferramenta"]["id"]) == 3, "5 - 2 entregues"
    movs = logado.get(f"/api/ferramentas/movimentos?ferramenta_id={c['ferramenta']['id']}").get_json()
    saida = next(m for m in movs if m["tipo"] == "saida")
    assert saida["quantidade"] == 2 and saida["entrega_id"] == entrega["id"]
    assert "Carlos Mecânico" in saida["documento"]

    por_mecanico = logado.get(
        f"/api/entregas_ferramenta?funcionario_id={c['mecanico']['id']}").get_json()
    assert [e["id"] for e in por_mecanico] == [entrega["id"]]


def test_entrega_sem_saldo_suficiente_nao_baixa_nem_registra(logado, cenario):
    c = cenario
    _abastecer(logado, c, 1)
    r = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["mecanico"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 2})
    assert r.status_code == 400 and "insuficiente" in r.get_json()["erro"].lower()
    assert _saldo(logado, c["ferramenta"]["id"]) == 1
    assert logado.get("/api/entregas_ferramenta").get_json() == []


def test_so_mecanico_recebe_ferramenta(logado, cenario):
    c = cenario
    _abastecer(logado, c, 3)
    r = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["motorista"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 1})
    assert r.status_code == 400 and "mecânico" in r.get_json()["erro"]
    assert _saldo(logado, c["ferramenta"]["id"]) == 3

    nomes = [m["nome"] for m in logado.get("/api/ferramentas/mecanicos").get_json()]
    assert nomes == ["Carlos Mecânico"]


def test_quantidade_zero_e_recusada_na_entrega(logado, cenario):
    c = cenario
    _abastecer(logado, c, 3)
    r = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["mecanico"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 0})
    assert r.status_code == 400
    assert _saldo(logado, c["ferramenta"]["id"]) == 3


def test_cancelar_entrega_devolve_ao_estoque(logado, cenario):
    c = cenario
    _abastecer(logado, c, 5)
    entrega = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["mecanico"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 3}).get_json()
    assert _saldo(logado, c["ferramenta"]["id"]) == 2

    r = logado.delete(f"/api/entregas_ferramenta/{entrega['id']}", headers=SENHA_ADMIN)
    assert r.status_code == 200
    assert _saldo(logado, c["ferramenta"]["id"]) == 5
    assert logado.get("/api/entregas_ferramenta").get_json() == []
    # o histórico continua mostrando a baixa e o estorno
    tipos = [m["tipo"] for m in logado.get(
        f"/api/ferramentas/movimentos?ferramenta_id={c['ferramenta']['id']}").get_json()]
    assert tipos.count("saida") == 1 and tipos.count("entrada") == 2


def test_exclusao_exige_senha_de_administrador(logado, cenario):
    c = cenario
    _abastecer(logado, c, 2)
    entrega = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["mecanico"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 1}).get_json()
    assert logado.delete(f"/api/entregas_ferramenta/{entrega['id']}").status_code == 403
    assert _saldo(logado, c["ferramenta"]["id"]) == 1


def test_ferramenta_inativa_nao_pode_ser_entregue(logado, cenario):
    c = cenario
    _abastecer(logado, c, 2)
    logado.put(f"/api/ferramentas/{c['ferramenta']['id']}", json={"ativo": False})
    r = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["mecanico"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 1})
    assert r.status_code == 400


# ------------------------------------------------------ ajuste e exclusão
def test_ajuste_de_inventario_exige_motivo(logado, cenario):
    c = cenario
    _abastecer(logado, c, 5)
    sem_motivo = logado.post("/api/ferramentas/ajuste", json={
        "ferramenta_id": c["ferramenta"]["id"], "quantidade": 4})
    assert sem_motivo.status_code == 400
    ok = logado.post("/api/ferramentas/ajuste", json={
        "ferramenta_id": c["ferramenta"]["id"], "quantidade": 4,
        "observacao": "Contagem do inventário"})
    assert ok.status_code == 200 and ok.get_json()["quantidade"] == 4


def test_ferramenta_com_historico_nao_pode_ser_excluida(logado, cenario):
    c = cenario
    _abastecer(logado, c, 1)
    r = logado.delete(f"/api/ferramentas/{c['ferramenta']['id']}", headers=SENHA_ADMIN)
    assert r.status_code == 400
    assert "desmarque" in r.get_json()["erro"].lower()


def test_ferramenta_sem_historico_pode_ser_excluida(logado):
    f = logado.post("/api/ferramentas", json={"descricao": "Alicate"}).get_json()
    assert logado.delete(f"/api/ferramentas/{f['id']}", headers=SENHA_ADMIN).status_code == 200


# ------------------------------------------------------------ permissões/tela
def test_pagina_abre_e_menu_tem_o_link(logado):
    r = logado.get("/ferramentas")
    assert r.status_code == 200
    assert "Ferramentas mecânicos" in r.get_data(as_text=True)


def test_usuario_sem_permissao_nao_acessa(logado, cliente):
    r = logado.post("/api/usuarios", json={
        "nome": "Sem Acesso", "email": "semacesso@teste.local",
        "perfil": "restrito", "senha": "senha123"})
    assert r.status_code == 201
    logado.get("/logout")
    assert cliente.post("/login", json={"email": "semacesso@teste.local",
                                        "senha": "senha123"}).status_code == 200
    assert cliente.get("/api/ferramentas").status_code == 403
    assert cliente.post("/api/entregas_ferramenta", json={}).status_code == 403


def test_usuario_so_visualiza_nao_da_baixa(logado, cliente, cenario):
    c = cenario
    _abastecer(logado, c, 3)
    r = logado.post("/api/usuarios", json={
        "nome": "Leitor", "email": "leitor@teste.local", "perfil": "restrito",
        "senha": "senha123",
        "permissoes": [{"tela": "ferramentas", "nivel": "visualizar"}]})
    assert r.status_code == 201, r.get_json()
    logado.get("/logout")
    cliente.post("/login", json={"email": "leitor@teste.local", "senha": "senha123"})
    assert cliente.get("/api/ferramentas").status_code == 200
    r = cliente.post("/api/entregas_ferramenta", json={
        "funcionario_id": c["mecanico"]["id"], "ferramenta_id": c["ferramenta"]["id"],
        "quantidade": 1})
    assert r.status_code == 403
