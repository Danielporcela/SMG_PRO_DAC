"""Ferramentas dos caminhões: lançamento por veículo com baixa no estoque de peças."""
from datetime import timedelta

from services.tempo import hoje

URL = "/api/ferramentas-caminhoes"
SENHA_ADMIN = {"X-SGMF-Admin-Password": "teste123"}


def _peca(logado, codigo, descricao, quantidade=10, custo=40):
    r = logado.post("/api/pecas", json={
        "codigo": codigo, "descricao": descricao, "grupo": "Ferramentas",
        "unidade": "UN", "custo_unitario": custo, "quantidade_inicial": quantidade})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _saldo(logado, peca):
    return logado.get(f"/api/pecas/{peca['id']}").get_json()["quantidade"]


def _lancar(logado, veiculo, itens, **extra):
    return logado.post(URL, json={"veiculo_id": veiculo["id"], "itens": itens, **extra})


def test_lancamento_baixa_estoque_de_pecas(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada", quantidade=10, custo=40)
    r = _lancar(logado, base["veiculo"], [{"peca_id": pa["id"], "quantidade": 3}],
                responsavel="Carlos", observacao="Rota centro")
    assert r.status_code == 201, r.get_json()
    uso = r.get_json()["lancamentos"][0]
    assert uso["quantidade"] == 3 and uso["custo_unitario"] == 40 and uso["valor_total"] == 120
    assert uso["responsavel"] == "Carlos" and uso["documento"] == f"FERR-VEIC-{uso['id']}"

    assert _saldo(logado, pa) == 7
    movimentos = logado.get("/api/movimentos").get_json()
    mov = next(m for m in movimentos if m["id"] == uso["movimento_estoque_id"])
    assert mov["tipo"] == "saida" and mov["quantidade"] == 3
    assert mov["documento"] == uso["documento"]
    assert "ABC1D23" in mov["observacao"] or "FR-001" in mov["observacao"]

    lista = logado.get(URL).get_json()
    assert len(lista) == 1 and lista[0]["veiculo_id"] == base["veiculo"]["id"]


def test_varias_ferramentas_no_mesmo_lancamento_e_repetidas_somam(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada", quantidade=10)
    enxada = _peca(logado, "EN-001", "Enxada", quantidade=5)
    r = _lancar(logado, base["veiculo"], [
        {"peca_id": pa["id"], "quantidade": 2},
        {"peca_id": enxada["id"], "quantidade": 1},
        {"peca_id": pa["id"], "quantidade": 1},      # repetida: soma 3
    ])
    assert r.status_code == 201, r.get_json()
    assert len(r.get_json()["lancamentos"]) == 2
    assert _saldo(logado, pa) == 7 and _saldo(logado, enxada) == 4


def test_tudo_ou_nada_quando_uma_ferramenta_nao_tem_saldo(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada", quantidade=10)
    rastelo = _peca(logado, "RA-001", "Rastelo", quantidade=2)
    r = _lancar(logado, base["veiculo"], [
        {"peca_id": pa["id"], "quantidade": 3},
        {"peca_id": rastelo["id"], "quantidade": 5},
    ])
    assert r.status_code == 400
    assert "insuficiente" in r.get_json()["erro"].lower()
    assert _saldo(logado, pa) == 10 and _saldo(logado, rastelo) == 2
    assert logado.get(URL).get_json() == []


def test_entradas_invalidas_nao_mexem_no_estoque(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada", quantidade=10)
    for qtd in (0, -1, "abc", "nan", "inf", None):
        r = _lancar(logado, base["veiculo"], [{"peca_id": pa["id"], "quantidade": qtd}])
        assert r.status_code == 400, qtd
    assert _lancar(logado, base["veiculo"], []).status_code == 400
    assert _lancar(logado, base["veiculo"], [{"peca_id": 999999, "quantidade": 1}]).status_code == 400
    assert logado.post(URL, json={"itens": [{"peca_id": pa["id"], "quantidade": 1}]}).status_code == 400
    futuro = (hoje() + timedelta(days=2)).isoformat()
    assert _lancar(logado, base["veiculo"], [{"peca_id": pa["id"], "quantidade": 1}],
                   data=futuro).status_code == 400
    assert _saldo(logado, pa) == 10
    assert logado.get(URL).get_json() == []


def test_data_retroativa_vale_no_historico_do_estoque(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada")
    ontem = (hoje() - timedelta(days=1)).isoformat()
    r = _lancar(logado, base["veiculo"], [{"peca_id": pa["id"], "quantidade": 1}], data=ontem)
    assert r.status_code == 201, r.get_json()
    uso = r.get_json()["lancamentos"][0]
    assert uso["data"] == ontem
    mov = next(m for m in logado.get("/api/movimentos").get_json()
               if m["id"] == uso["movimento_estoque_id"])
    assert mov["data"] == ontem


def test_veiculo_inativo_e_recusado(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada")
    v = base["veiculo"]
    assert logado.put(f"/api/veiculos/{v['id']}", json={"ativo": False}).status_code == 200
    r = _lancar(logado, v, [{"peca_id": pa["id"], "quantidade": 1}])
    assert r.status_code == 400 and "inativo" in r.get_json()["erro"].lower()
    assert _saldo(logado, pa) == 10
    # e some da lista de caminhões do lançamento
    assert all(x["id"] != v["id"] for x in logado.get(f"{URL}/veiculos").get_json())


def test_item_com_rastreio_por_serie_e_recusado(logado, base):
    r = logado.post("/api/pecas", json={
        "codigo": "SER-001", "descricao": "Item serializado", "grupo": "Ferramentas",
        "unidade": "UN", "custo_unitario": 10, "quantidade_inicial": 2,
        "numeros_serie": "SER-0001\nSER-0002"})
    assert r.status_code == 201, r.get_json()
    peca = r.get_json()
    resp = _lancar(logado, base["veiculo"], [{"peca_id": peca["id"], "quantidade": 1}])
    assert resp.status_code == 400 and "série" in resp.get_json()["erro"].lower()
    assert _saldo(logado, peca) == 2


def test_busca_de_pecas_ignora_acento_e_filtra_por_grupo(logado, base):
    _peca(logado, "PA-001", "Pá quadrada")
    _peca(logado, "GA-001", "Garfo de jardim")
    achadas = logado.get(f"{URL}/pecas?q=pa quadrada").get_json()
    assert [p["codigo"] for p in achadas["pecas"]] == ["PA-001"]
    assert achadas["pecas"][0]["quantidade"] == 10
    todas = logado.get(f"{URL}/pecas?grupo=Ferramentas").get_json()
    assert {p["codigo"] for p in todas["pecas"]} == {"PA-001", "GA-001"}
    assert "Ferramentas" in logado.get(f"{URL}/grupos").get_json()


def test_cancelar_devolve_ao_estoque_e_exige_senha_de_admin(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada", quantidade=10)
    uso = _lancar(logado, base["veiculo"],
                  [{"peca_id": pa["id"], "quantidade": 4}]).get_json()["lancamentos"][0]
    assert _saldo(logado, pa) == 6

    # sem a senha do administrador a exclusão não passa
    assert logado.delete(f"{URL}/{uso['id']}").status_code == 403
    assert _saldo(logado, pa) == 6

    r = logado.delete(f"{URL}/{uso['id']}", headers=SENHA_ADMIN)
    assert r.status_code == 200, r.get_json()
    assert _saldo(logado, pa) == 10

    # segunda tentativa não devolve de novo
    r2 = logado.delete(f"{URL}/{uso['id']}", headers=SENHA_ADMIN)
    assert r2.status_code == 400 and "já foi cancelado" in r2.get_json()["erro"].lower()
    assert _saldo(logado, pa) == 10

    # some da lista normal, mas continua no histórico quando pedido
    assert logado.get(URL).get_json() == []
    todos = logado.get(f"{URL}?incluir_cancelados=1").get_json()
    assert len(todos) == 1 and todos[0]["situacao"] == "Cancelado"
    # o estoque registra a devolução como entrada
    entradas = [m for m in logado.get("/api/movimentos").get_json()
                if m["tipo"] == "entrada" and f"FERR-VEIC-{uso['id']}" in (m["documento"] or "")]
    assert len(entradas) == 1 and entradas[0]["quantidade"] == 4


def test_resumo_por_caminhao_ignora_cancelados(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada", custo=40)
    enxada = _peca(logado, "EN-001", "Enxada", custo=25)
    veiculo = base["veiculo"]
    a = _lancar(logado, veiculo, [{"peca_id": pa["id"], "quantidade": 2}]).get_json()["lancamentos"][0]
    _lancar(logado, veiculo, [{"peca_id": enxada["id"], "quantidade": 2}])
    resumo = logado.get(f"{URL}/resumo").get_json()
    assert resumo["total_valor"] == 130 and resumo["total_quantidade"] == 4
    assert resumo["total_lancamentos"] == 2
    assert resumo["veiculos"][0]["veiculo_id"] == veiculo["id"]

    logado.delete(f"{URL}/{a['id']}", headers=SENHA_ADMIN)
    resumo = logado.get(f"{URL}/resumo").get_json()
    assert resumo["total_valor"] == 50 and resumo["total_lancamentos"] == 1

    ontem = (hoje() - timedelta(days=1)).isoformat()
    vazio = logado.get(f"{URL}/resumo?inicio={ontem}&fim={ontem}").get_json()
    assert vazio["total_valor"] == 0 and vazio["veiculos"] == []


def test_nao_aparece_no_top_de_pecas_do_painel(logado, base):
    pa = _peca(logado, "PA-001", "Pá quadrada exclusiva", quantidade=10)
    assert _lancar(logado, base["veiculo"], [{"peca_id": pa["id"], "quantidade": 3}]).status_code == 201
    grafico = logado.get("/api/painel/graficos").get_json()
    assert all("Pá quadrada exclusiva" not in i["peca"] for i in grafico["top_pecas"])


# ------------------------------------------------------------- permissões
def _usuario(logado, cliente, email, permissoes):
    r = logado.post("/api/usuarios", json={
        "nome": email.split("@")[0].title(), "email": email, "perfil": "restrito",
        "senha": "senha123", "permissoes": permissoes})
    assert r.status_code == 201, r.get_json()
    logado.get("/logout")
    assert cliente.post("/login", json={"email": email, "senha": "senha123"}).status_code == 200


def test_sem_permissao_nao_acessa_tela_nem_api(logado, cliente, base):
    _usuario(logado, cliente, "semacesso@teste.local",
             [{"tela": "manutencao", "nivel": "visualizar"}])
    assert cliente.get(URL).status_code == 403
    assert cliente.get(f"{URL}/veiculos").status_code == 403
    assert cliente.post(URL, json={}).status_code == 403
    assert cliente.get("/ferramentas-caminhoes").status_code in (302, 403)


def test_visualizar_lista_mas_nao_lanca_nem_cancela(logado, cliente, base):
    pa = _peca(logado, "PA-001", "Pá quadrada")
    uso = _lancar(logado, base["veiculo"],
                  [{"peca_id": pa["id"], "quantidade": 1}]).get_json()["lancamentos"][0]
    _usuario(logado, cliente, "leitor@teste.local",
             [{"tela": "ferramentas_caminhoes", "nivel": "visualizar"}])
    assert cliente.get(URL).status_code == 200
    assert cliente.get(f"{URL}/pecas?q=pa").status_code == 200
    assert cliente.get("/ferramentas-caminhoes").status_code == 200
    r = cliente.post(URL, json={"veiculo_id": base["veiculo"]["id"],
                                "itens": [{"peca_id": pa["id"], "quantidade": 1}]})
    assert r.status_code == 403
    assert cliente.delete(f"{URL}/{uso['id']}", headers=SENHA_ADMIN).status_code == 403


def test_editar_lanca_ferramenta(logado, cliente, base):
    pa = _peca(logado, "PA-001", "Pá quadrada")
    _usuario(logado, cliente, "almox@teste.local",
             [{"tela": "ferramentas_caminhoes", "nivel": "editar"}])
    r = cliente.post(URL, json={"veiculo_id": base["veiculo"]["id"],
                                "itens": [{"peca_id": pa["id"], "quantidade": 2}]})
    assert r.status_code == 201, r.get_json()
    assert r.get_json()["lancamentos"][0]["usuario_nome"] == "Almox"
