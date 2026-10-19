"""Integração de ferramentas dos mecânicos com peças e custos do painel."""
from datetime import timedelta

from services.tempo import hoje


def _produto(logado, codigo="FERR-PEC-001", preco=140, quantidade=8):
    r = logado.post("/api/pecas", json={
        "codigo": codigo, "descricao": f"Jogo de chaves combinado {codigo}",
        "unidade": "UN", "grupo": "Ferramentas", "custo_unitario": preco,
        "quantidade_inicial": quantidade,
        "numeros_serie": "\n".join(f"{codigo}-{i:04d}" for i in range(1, quantidade + 1))})
    assert r.status_code == 201, r.get_json()
    return r.get_json()


def _baixar(logado, produto_id, quantidade=2):
    seriais = logado.get(f"/api/ferramentas/pecas/{produto_id}/seriais").get_json()["seriais"]
    selecionados = [s["id"] for s in seriais[:quantidade]] if isinstance(quantidade, int) and quantidade > 0 else []
    return logado.post("/api/ferramentas/inserir-do-estoque", json={
        "peca_id": produto_id, "quantidade": quantidade,
        "observacao": "Entrega de material à oficina", "seriais_ids": selecionados})


def test_transferencia_diminui_pecas_e_aumenta_ferramentas(logado):
    p = _produto(logado)
    r = _baixar(logado, p["id"], 3)
    assert r.status_code == 201, r.get_json()
    t = r.get_json()["transferencia"]
    f = r.get_json()["ferramenta"]
    assert t["quantidade"] == 3 and t["valor_total"] == 420
    assert t["custo_unitario"] == 140
    assert f["quantidade"] == 3 and f["descricao"] == p["descricao"]
    assert logado.get(f"/api/pecas/{p['id']}").get_json()["quantidade"] == 5
    rastreio = logado.get(f"/api/pecas/{p['id']}/rastreio").get_json()
    assert sum(r["status"] == "Transferida" for r in rastreio["resultados"]) == 3
    movimentos = logado.get("/api/movimentos").get_json()
    assert any(m["id"] == t["movimento_estoque_id"] and m["tipo"] == "saida" and
               m["documento"] == f"FERR-MEC-{t['id']}" for m in movimentos)
    movs_f = logado.get(f"/api/ferramentas/movimentos?ferramenta_id={f['id']}").get_json()
    assert len(movs_f) == 1 and movs_f[0]["tipo"] == "entrada"
    assert movs_f[0]["documento"] == f"FERR-MEC-{t['id']}"
    lista = logado.get("/api/ferramentas/transferencias-pecas").get_json()
    assert len(lista) == 1 and lista[0]["valor_total"] == 420


def test_reutiliza_mesma_ferramenta_sem_duplicar_cadastros(logado):
    p = _produto(logado)
    f1 = _baixar(logado, p["id"], 2).get_json()["ferramenta"]
    f2 = _baixar(logado, p["id"], 1).get_json()["ferramenta"]
    assert f1["id"] == f2["id"]
    assert f2["quantidade"] == 3
    assert len(logado.get("/api/ferramentas").get_json()) == 1
    assert len(logado.get("/api/ferramentas/transferencias-pecas").get_json()) == 2


def test_estoque_insuficiente_reverte_tudo(logado):
    p = _produto(logado, quantidade=2)
    r = _baixar(logado, p["id"], 3)
    assert r.status_code == 400
    assert "insuficiente" in r.get_json()["erro"].lower()
    assert logado.get(f"/api/pecas/{p['id']}").get_json()["quantidade"] == 2
    assert logado.get("/api/ferramentas").get_json() == []
    assert logado.get("/api/ferramentas/transferencias-pecas").get_json() == []


def test_quantidades_invalidas_nao_alteram_estq(logado):
    p = _produto(logado)
    for qtd in (0, -5, "abc", "nan", "inf", None):
        assert _baixar(logado, p["id"], qtd).status_code == 400
    assert logado.get(f"/api/pecas/{p['id']}").get_json()["quantidade"] == 8
    assert logado.get("/api/ferramentas").get_json() == []


def test_painel_soma_sem_duplica_entrega(logado):
    p = _produto(logado, preco=75, quantidade=7)
    d0 = logado.get("/api/painel/resumo").get_json()
    assert d0["gasto_ferramentas_mecanicos"] == 0
    r = _baixar(logado, p["id"], 4)
    assert r.status_code == 201, r.get_json()
    f = r.get_json()["ferramenta"]
    d = logado.get("/api/painel/resumo").get_json()
    assert d["gasto_ferramentas_mecanicos"] == 300
    assert d["transferencias_ferramentas_qtd"] == 1
    assert d["gasto_total"] == d0["gasto_total"] + 300
    # O indicador geral histórico já inclui NFs de compra de peças.
    # Uma mera transferência interna não deve duplicar essa compra.
    assert d["gasto_total_geral"] == d0["gasto_total_geral"]
    mecanico = logado.post("/api/funcionarios", json={"nome": "Mecânico Oficina",
                                 "cargo": "Mecânico", "ativo": True}).get_json()
    entrega = logado.post("/api/entregas_ferramenta", json={
        "funcionario_id": mecanico["id"], "ferramenta_id": f["id"],
        "quantidade": 2})
    assert entrega.status_code == 201, entrega.get_json()
    assert logado.get("/api/painel/resumo").get_json()["gasto_total"] == d["gasto_total"]
    assert logado.get(f"/api/ferramentas/{f['id']}").get_json()["quantidade"] == 2
    grafico = logado.get("/api/painel/graficos").get_json()
    assert sum(grafico["ferramentas_mes"]) == 300
    assert all("Jogo de chaves combinado" not in i["peca"] for i in grafico["top_pecas"])


def test_filtro_periodo_respeita_data_da_transferencia(logado):
    p = _produto(logado)
    assert _baixar(logado, p["id"]).status_code == 201
    ontem = (hoje() - timedelta(days=1)).isoformat()
    d = logado.get(f"/api/painel/resumo?inicio={ontem}&fim={ontem}").get_json()
    assert d["gasto_ferramentas_mecanicos"] == 0
    assert d["transferencias_ferramentas_qtd"] == 0
    hoje_str = hoje().isoformat()
    d = logado.get(f"/api/painel/resumo?inicio={hoje_str}&fim={hoje_str}").get_json()
    assert d["gasto_ferramentas_mecanicos"] == 280


def test_lista_pecas_somente_saldo_positivo(logado):
    p1 = _produto(logado, "FERR-PEC-002")
    _produto(logado, "FERR-PEC-003", quantidade=0)
    lista = logado.get("/api/ferramentas/pecas-disponiveis")
    assert lista.status_code == 200
    assert [p["id"] for p in lista.get_json()] == [p1["id"]]


def test_serial_obrigatorio_quando_existe_rastreio(logado):
    p = _produto(logado)
    resposta = logado.post("/api/ferramentas/inserir-do-estoque", json={
        "peca_id": p["id"], "quantidade": 2})
    assert resposta.status_code == 400
    assert "identificação" in resposta.get_json()["erro"]
    assert logado.get(f"/api/pecas/{p['id']}").get_json()["quantidade"] == 8


def test_sem_permissao_estoque_nao_autoriza_baixa(logado, cliente):
    r = logado.post("/api/usuarios", json={
        "nome": "Controle ferramentas", "email": "ferrtools@teste.local",
        "senha": "senha123", "perfil": "restrito", "permissoes": [
            {"tela": "ferramentas", "nivel": "editar"}]})
    assert r.status_code == 201, r.get_json()
    logado.get("/logout")
    assert cliente.post("/login", json={
        "email": "ferrtools@teste.local", "senha": "senha123"}).status_code == 200
    assert cliente.get("/api/ferramentas/pecas-disponiveis").status_code == 403
    assert cliente.post("/api/ferramentas/inserir-do-estoque",
                        json={"peca_id": 1, "quantidade": 1}).status_code == 403


def test_transferencia_de_estoque_legado_sem_serial(logado):
    p = logado.post("/api/pecas", json={
        "descricao": "Ferramenta antiga sem identificação",
        "unidade": "UN", "custo_unitario": 60}).get_json()
    assert "id" in p, p
    assert logado.post("/api/movimentos", json={
        "peca_id": p["id"], "tipo": "entrada", "quantidade": 5,
        "custo_unitario": 60}).status_code == 201
    identificacoes = logado.get(f"/api/ferramentas/pecas/{p['id']}/seriais").get_json()
    assert identificacoes == {"rastreado": False, "seriais": []}
    r = logado.post("/api/ferramentas/inserir-do-estoque", json={
        "peca_id": p["id"], "quantidade": 2})
    assert r.status_code == 201, r.get_json()
    assert logado.get(f"/api/pecas/{p['id']}").get_json()["quantidade"] == 3
    assert r.get_json()["transferencia"]["valor_total"] == 120


def test_modal_de_transferencia_disponivel_na_tela(logado):
    r = logado.get("/ferramentas")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="botaoInserirFerramentaPeca"' in html
    assert 'id="transferirSeriais"' in html
    assert 'id="transferirSalvar"' in html
    assert "gasto" in html.lower()
