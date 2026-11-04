"""Painel lateral "Boletos a vencer": filtro por período (De / Até)."""


def _nota_com_parcelas(logado, fornecedor_id, numero, vencimentos):
    nota = logado.post("/api/notas_fiscais", json={
        "numero": numero, "fornecedor_id": fornecedor_id}).get_json()
    for data, valor in vencimentos:
        r = logado.post(f"/api/notas_fiscais/{nota['id']}/parcelas",
                        json={"data_vencimento": data, "valor": valor})
        assert r.status_code in (200, 201), r.get_json()
    return nota


def _consultar(logado, **filtros):
    resposta = logado.get("/api/parcelas_nota/a_vencer", query_string=filtros)
    assert resposta.status_code == 200, resposta.get_json()
    return resposta.get_json()


def test_periodo_traz_todos_os_vencimentos_do_mes_em_ordem(logado, base):
    forn = base["oficina"]["id"]
    _nota_com_parcelas(logado, forn, "100", [
        ("2099-10-20", 50), ("2099-11-01", 100), ("2099-11-15", 200)])
    _nota_com_parcelas(logado, forn, "101", [
        ("2099-11-30", 300), ("2099-12-05", 400)])

    dados = _consultar(logado, inicio="2099-11-01", fim="2099-11-30")

    datas = [i["data_vencimento"] for i in dados["itens"]]
    assert datas == ["2099-11-01", "2099-11-15", "2099-11-30"]
    assert dados["qtd"] == 3
    assert dados["total"] == 600


def test_parcela_paga_sai_da_lista(logado, base):
    forn = base["oficina"]["id"]
    nota = _nota_com_parcelas(logado, forn, "102", [("2099-11-10", 80), ("2099-11-20", 90)])
    parcelas = logado.get(f"/api/notas_fiscais/{nota['id']}").get_json()["parcelas"]
    logado.post(f"/api/notas_fiscais/{nota['id']}/parcelas/{parcelas[0]['id']}/pagar", json={})

    dados = _consultar(logado, inicio="2099-11-01", fim="2099-11-30")

    assert [i["data_vencimento"] for i in dados["itens"]] == ["2099-11-20"]
    assert dados["total"] == 90


def test_vencidas_anteriores_so_entram_se_pedido(logado, base):
    forn = base["oficina"]["id"]
    _nota_com_parcelas(logado, forn, "103", [("2000-01-10", 70), ("2099-11-05", 10)])

    sem = _consultar(logado, inicio="2099-11-01", fim="2099-11-30")
    com = _consultar(logado, inicio="2099-11-01", fim="2099-11-30", vencidas="1")

    assert [i["data_vencimento"] for i in sem["itens"]] == ["2099-11-05"]
    assert [i["data_vencimento"] for i in com["itens"]] == ["2000-01-10", "2099-11-05"]


def test_data_inicial_maior_que_final_e_recusada(logado):
    r = logado.get("/api/parcelas_nota/a_vencer",
                   query_string={"inicio": "2099-11-30", "fim": "2099-11-01"})
    assert r.status_code == 400


def test_consulta_antiga_por_data_continua_funcionando(logado, base):
    forn = base["oficina"]["id"]
    _nota_com_parcelas(logado, forn, "104", [("2099-11-05", 10), ("2099-11-06", 20)])

    dados = _consultar(logado, data="2099-11-05", modo="na")

    assert dados["qtd"] == 1


def test_pagina_de_boletos_abre_para_quem_esta_logado(logado):
    r = logado.get("/boletos?inicio=2099-11-01&fim=2099-11-30")
    assert r.status_code == 200
    assert b"tabelaBoletos" in r.data or "Boletos a vencer".encode() in r.data


def test_pagina_de_boletos_exige_login(cliente):
    r = cliente.get("/boletos")
    assert r.status_code in (301, 302)


def test_menu_lateral_tem_link_direto_para_a_pagina_de_boletos(logado):
    html = logado.get("/").data.decode("utf-8")
    assert 'href="/boletos"' in html
    assert 'id="vencContador"' in html
