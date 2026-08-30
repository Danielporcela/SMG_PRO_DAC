"""Regras de negócio — é aqui que o sistema calcula sozinho."""
from datetime import timedelta

from services.tempo import hoje as data_de_hoje


# ---------------------------------------------------------------- combustível
def test_calculo_de_consumo_entre_abastecimentos(logado, base):
    vid = base["veiculo"]["id"]
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 100000,
                                             "litros": 100, "valor_litro": 6})
    segundo = logado.post("/api/abastecimentos", json={
        "veiculo_id": vid, "km_atual": 100300, "litros": 100, "valor_litro": 6}).get_json()

    assert segundo["km_percorridos"] == 300
    assert segundo["km_por_litro"] == 3.0          # 300 km / 100 L
    assert segundo["valor_total"] == 600.0         # 100 L x R$ 6
    assert segundo["custo_por_km"] == 2.0          # R$ 600 / 300 km


def test_valor_do_litro_calculado_a_partir_do_total(logado, base):
    r = logado.post("/api/abastecimentos", json={"veiculo_id": base["veiculo"]["id"],
                                                 "km_atual": 100200, "litros": 50,
                                                 "valor_total": 300}).get_json()
    assert r["valor_litro"] == 6.0


def test_km_menor_que_o_ultimo_e_recusado(logado, base):
    vid = base["veiculo"]["id"]
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 100500,
                                             "litros": 80, "valor_litro": 6})
    r = logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 99000,
                                                 "litros": 80, "valor_litro": 6})
    assert r.status_code == 400
    assert "menor que o último" in r.get_json()["erro"]


def test_hodometro_do_veiculo_acompanha_o_abastecimento(logado, base):
    vid = base["veiculo"]["id"]
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 123456,
                                             "litros": 90, "valor_litro": 6})
    assert logado.get(f"/api/veiculos/{vid}").get_json()["hodometro"] == 123456


def test_abastecimento_exige_veiculo_km_e_litros(logado):
    r = logado.post("/api/abastecimentos", json={"litros": 50})
    assert r.status_code == 400


def test_filtro_de_periodo_nos_abastecimentos(logado, base):
    vid = base["veiculo"]["id"]
    hoje = data_de_hoje()
    antigo = (hoje - timedelta(days=120)).isoformat()
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 100100,
                                             "litros": 50, "valor_litro": 6, "data": antigo})
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 100900,
                                             "litros": 50, "valor_litro": 6,
                                             "data": hoje.isoformat()})
    inicio = hoje.replace(day=1).isoformat()
    lista = logado.get(f"/api/abastecimentos?inicio={inicio}&fim={hoje}").get_json()
    assert len(lista) == 1


# ----------------------------------------------------------------- manutenção
def test_numero_da_os_gerado_automaticamente(logado, base):
    r = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"],
                                         "tipo": "Corretiva"}).get_json()
    assert r["numero"].startswith(f"OS{data_de_hoje().year}")
    assert r["numero"].endswith("00001")

    segunda = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    assert segunda["numero"].endswith("00002")


def test_veiculo_entra_e_sai_de_manutencao(logado, base):
    vid = base["veiculo"]["id"]
    os_criada = logado.post("/api/ordens", json={"veiculo_id": vid, "status": "Aberta"}).get_json()
    assert logado.get(f"/api/veiculos/{vid}").get_json()["situacao"] == "Em manutenção"

    logado.put(f"/api/ordens/{os_criada['id']}", json={"status": "Finalizada"})
    assert logado.get(f"/api/veiculos/{vid}").get_json()["situacao"] == "Disponível"


def test_data_de_fechamento_preenchida_ao_finalizar(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    assert os_criada["data_fechamento"] is None
    fechada = logado.put(f"/api/ordens/{os_criada['id']}",
                         json={"status": "Finalizada"}).get_json()
    assert fechada["data_fechamento"] == data_de_hoje().isoformat()


def test_preventiva_finalizada_atualiza_o_veiculo(logado, base):
    vid = base["veiculo"]["id"]
    os_criada = logado.post("/api/ordens", json={"veiculo_id": vid, "tipo": "Preventiva",
                                                 "grupo": "Motor", "km_veiculo": 105000,
                                                 "descricao": "Troca de óleo e filtros"}).get_json()
    logado.put(f"/api/ordens/{os_criada['id']}", json={"status": "Finalizada"})
    veiculo = logado.get(f"/api/veiculos/{vid}").get_json()
    assert veiculo["data_ultima_preventiva"] == data_de_hoje().isoformat()
    assert veiculo["km_ultima_troca_oleo"] == 105000
    assert veiculo["hodometro"] == 105000


def test_custo_total_da_os_soma_pecas_mao_de_obra_e_servicos(logado, base):
    os_criada = logado.post("/api/ordens", json={
        "veiculo_id": base["veiculo"]["id"], "custo_mao_obra": 200,
        "custo_servicos": 150}).get_json()

    logado.post(f"/api/ordens/{os_criada['id']}/itens",
                json={"peca_id": base["peca"]["id"], "quantidade": 3})
    atualizada = logado.get(f"/api/ordens/{os_criada['id']}").get_json()

    assert atualizada["custo_pecas"] == 150.0      # 3 x R$ 50
    assert atualizada["custo_total"] == 500.0      # 150 + 200 + 150


def test_dias_parado(logado, base):
    abertura = (data_de_hoje() - timedelta(days=5)).isoformat()
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"],
                                                 "data_abertura": abertura}).get_json()
    assert os_criada["dias_parado"] == 5


def test_item_avulso_sem_peca_do_estoque(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    r = logado.post(f"/api/ordens/{os_criada['id']}/itens",
                    json={"descricao": "Solda do escapamento", "quantidade": 1,
                          "valor_unitario": 320})
    assert r.status_code == 201
    item = r.get_json()["itens"][0]
    assert item["baixado_estoque"] is False
    assert item["valor_total"] == 320.0


def test_item_sem_descricao_e_recusado(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    r = logado.post(f"/api/ordens/{os_criada['id']}/itens", json={"quantidade": 1})
    assert r.status_code == 400


# -------------------------------------------------------------------- estoque
def test_saldo_inicial_vira_movimento_de_entrada(logado, base):
    peca = logado.get(f"/api/pecas/{base['peca']['id']}").get_json()
    assert peca["quantidade"] == 20
    movimentos = logado.get("/api/movimentos").get_json()
    assert movimentos[0]["tipo"] == "entrada"
    assert movimentos[0]["quantidade"] == 20


def test_peca_lancada_na_os_fica_pendente_ate_finalizacao(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    resposta = logado.post(f"/api/ordens/{os_criada['id']}/itens",
                           json={"peca_id": base["peca"]["id"], "quantidade": 5}).get_json()

    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 20
    assert resposta["itens"][0]["baixado_estoque"] is False
    assert resposta["itens"][0]["descricao"] == "Filtro de óleo"
    assert resposta["itens"][0]["valor_unitario"] == 50.0

    finalizada = logado.put(f"/api/ordens/{os_criada['id']}",
                            json={"status": "Finalizada"})
    assert finalizada.status_code == 200
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 15
    detalhes = logado.get(f"/api/ordens/{os_criada['id']}/itens").get_json()
    assert detalhes["itens"][0]["baixado_estoque"] is True


def test_finalizar_a_mesma_os_duas_vezes_nao_duplica_baixa(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    logado.post(f"/api/ordens/{os_criada['id']}/itens",
                json={"peca_id": base["peca"]["id"], "quantidade": 5})

    primeira = logado.put(f"/api/ordens/{os_criada['id']}", json={"status": "Finalizada"})
    segunda = logado.put(f"/api/ordens/{os_criada['id']}", json={"status": "Finalizada"})

    assert primeira.status_code == 200
    assert segunda.status_code == 200
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 15


def test_finalizacao_com_estoque_insuficiente_faz_rollback(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    logado.post(f"/api/ordens/{os_criada['id']}/itens",
                json={"peca_id": base["peca"]["id"], "quantidade": 25})

    resposta = logado.put(f"/api/ordens/{os_criada['id']}", json={"status": "Finalizada"})

    assert resposta.status_code == 400
    assert "insuficiente" in resposta.get_json()["erro"]
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 20
    ordem = logado.get(f"/api/ordens/{os_criada['id']}").get_json()
    assert ordem["status"] == "Aberta"
    assert ordem["data_fechamento"] is None


def test_remover_item_devolve_a_peca_ao_estoque(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    itens = logado.post(f"/api/ordens/{os_criada['id']}/itens",
                        json={"peca_id": base["peca"]["id"], "quantidade": 5}).get_json()["itens"]
    logado.delete(f"/api/ordens/{os_criada['id']}/itens/{itens[0]['id']}")
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 20


def test_excluir_a_os_devolve_todas_as_pecas(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    logado.post(f"/api/ordens/{os_criada['id']}/itens",
                json={"peca_id": base["peca"]["id"], "quantidade": 8})
    logado.delete(f"/api/ordens/{os_criada['id']}")
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 20


def test_saida_maior_que_o_saldo_e_recusada(logado, base):
    r = logado.post("/api/movimentos", json={"peca_id": base["peca"]["id"],
                                             "tipo": "saida", "quantidade": 100})
    assert r.status_code == 400
    assert "insuficiente" in r.get_json()["erro"]
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 20


def test_entrada_recalcula_o_custo_medio(logado, base):
    # 20 un a R$ 50 + 20 un a R$ 70 => custo médio R$ 60
    logado.post("/api/movimentos", json={"peca_id": base["peca"]["id"], "tipo": "entrada",
                                         "quantidade": 20, "custo_unitario": 70})
    peca = logado.get(f"/api/pecas/{base['peca']['id']}").get_json()
    assert peca["quantidade"] == 40
    assert peca["custo_unitario"] == 60.0
    assert peca["valor_total"] == 2400.0


def test_ajuste_define_o_saldo(logado, base):
    logado.post("/api/movimentos", json={"peca_id": base["peca"]["id"], "tipo": "ajuste",
                                         "quantidade": 7, "observacao": "Inventário"})
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 7


def test_aviso_de_estoque_minimo(logado, base):
    logado.post("/api/movimentos", json={"peca_id": base["peca"]["id"], "tipo": "ajuste",
                                         "quantidade": 3})
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["abaixo_minimo"] is True


def test_quantidade_zero_ou_negativa_e_recusada(logado, base):
    r = logado.post("/api/movimentos", json={"peca_id": base["peca"]["id"],
                                             "tipo": "entrada", "quantidade": 0})
    assert r.status_code == 400


def test_codigo_de_peca_duplicado(logado, base):
    r = logado.post("/api/pecas", json={"codigo": "FIL-001", "descricao": "Outro filtro"})
    assert r.status_code == 400


# ---------------------------------------------------------------------- pneus
def test_pneu_abaixo_do_sulco_minimo_pede_troca(logado, base):
    critico = logado.post("/api/pneus", json={"numero_fogo": "P001", "sulco_mm": 3.2,
                                              "veiculo_id": base["veiculo"]["id"],
                                              "posicao": "Dianteiro Direito",
                                              "status": "Em uso"}).get_json()
    normal = logado.post("/api/pneus", json={"numero_fogo": "P002", "sulco_mm": 9.5,
                                             "status": "Em uso"}).get_json()
    assert critico["trocar"] is True
    assert normal["trocar"] is False


def test_pneu_em_estoque_nao_gera_alerta_de_troca(logado):
    pneu = logado.post("/api/pneus", json={"numero_fogo": "P003", "sulco_mm": 1.0,
                                           "status": "Estoque"}).get_json()
    assert pneu["trocar"] is False


def test_km_rodados_do_pneu(logado, base):
    pneu = logado.post("/api/pneus", json={"numero_fogo": "P004", "sulco_mm": 8,
                                           "veiculo_id": base["veiculo"]["id"],
                                           "km_instalacao": 60000}).get_json()
    assert pneu["km_rodados"] == 40000   # hodômetro 100.000 - instalação 60.000


def test_numero_de_fogo_duplicado(logado):
    logado.post("/api/pneus", json={"numero_fogo": "P010", "sulco_mm": 8})
    assert logado.post("/api/pneus", json={"numero_fogo": "P010"}).status_code == 400
