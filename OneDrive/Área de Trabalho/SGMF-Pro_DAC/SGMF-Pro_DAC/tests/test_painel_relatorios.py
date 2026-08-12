"""Painel executivo, alertas automáticos e exportação de relatórios."""
from datetime import timedelta

from services.tempo import hoje as data_de_hoje

import pytest


@pytest.fixture()
def movimentado(logado, base):
    """Uma frota com lançamentos suficientes para calcular indicadores."""
    vid = base["veiculo"]["id"]
    hoje = data_de_hoje()
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "motorista_id": base["motorista"]["id"],
                                             "km_atual": 100000, "litros": 100, "valor_litro": 6,
                                             "data": hoje.isoformat()})
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "motorista_id": base["motorista"]["id"],
                                             "km_atual": 100400, "litros": 100, "valor_litro": 6,
                                             "data": hoje.isoformat()})
    os_criada = logado.post("/api/ordens", json={"veiculo_id": vid, "tipo": "Corretiva",
                                                 "grupo": "Freios", "custo_mao_obra": 300,
                                                 "custo_servicos": 100}).get_json()
    logado.post(f"/api/ordens/{os_criada['id']}/itens",
                json={"peca_id": base["peca"]["id"], "quantidade": 2})
    logado.put(f"/api/ordens/{os_criada['id']}", json={"status": "Finalizada"})
    logado.post("/api/orcamentos", json={"ano": hoje.year, "mes": hoje.month,
                                         "categoria": "Geral", "meta_valor": 2000})
    logado.post("/api/pneus", json={"numero_fogo": "P900", "veiculo_id": vid,
                                    "posicao": "Dianteiro Direito", "sulco_mm": 7.5,
                                    "medida": "275/80 R22.5", "km_instalacao": 90000})
    return base


def test_resumo_do_painel(logado, movimentado):
    d = logado.get("/api/painel/resumo").get_json()
    assert d["veiculos_total"] == 1
    assert d["abastecimentos"] == 2
    assert d["litros"] == 200.0
    assert d["km_rodados"] == 400
    assert d["gasto_combustivel"] == 1200.0
    assert d["gasto_manutencao"] == 500.0        # 2 peças x 50 + 300 + 100
    assert d["gasto_total"] == 1700.0
    assert d["consumo_medio"] == 2.0             # 400 km / 200 L
    assert d["custo_por_km"] == 4.25             # R$ 1.700 / 400 km
    assert d["orcamento_mes"] == 2000.0
    assert d["aderencia_orcamento"] == 85.0
    assert 0 <= d["disponibilidade"] <= 100


def test_indicadores_de_manutencao(logado, movimentado):
    d = logado.get("/api/painel/resumo").get_json()
    assert d["os_corretivas"] == 1
    assert d["os_preventivas"] == 0
    assert d["os_abertas"] == 0
    assert d["mttr_dias"] >= 0
    assert d["estoque_valor"] == 900.0           # 18 un restantes x R$ 50


def test_painel_sem_lancamentos_nao_quebra(logado):
    d = logado.get("/api/painel/resumo").get_json()
    assert d["gasto_total"] == 0
    assert d["custo_por_km"] == 0
    assert d["consumo_medio"] == 0


def test_graficos_do_painel(logado, movimentado):
    g = logado.get("/api/painel/graficos").get_json()
    assert len(g["meses"]) == 12
    assert len(g["combustivel_mes"]) == 12
    assert g["tipos_manutencao"]["Corretiva"] == 1
    assert g["por_veiculo"][0]["total"] == 1700.0
    assert g["por_veiculo"][0]["consumo"] == 2.0
    assert "Freios" in g["grupos"]["labels"] or "Motor" in g["grupos"]["labels"]


def test_rankings(logado, movimentado):
    r = logado.get("/api/painel/rankings").get_json()
    assert r["melhor_consumo"][0]["nome"] == "João da Silva"
    assert r["melhor_consumo"][0]["consumo"] == 2.0
    assert r["veiculos_caros"][0]["veiculo"] == "FR-001"
    assert "maior_tempo_parado" in r


def test_alerta_de_troca_de_oleo_vencida(logado, base):
    logado.put(f"/api/veiculos/{base['veiculo']['id']}", json={"hodometro": 120000})
    alertas = logado.get("/api/painel/alertas").get_json()
    oleo = [a for a in alertas if a["categoria"] == "Óleo"]
    assert oleo and oleo[0]["nivel"] == "critico"
    assert "vencida" in oleo[0]["titulo"]


def test_alerta_de_troca_de_oleo_proxima(logado, base):
    logado.put(f"/api/veiculos/{base['veiculo']['id']}", json={"hodometro": 104700})
    alertas = logado.get("/api/painel/alertas").get_json()
    oleo = [a for a in alertas if a["categoria"] == "Óleo"]
    assert oleo and oleo[0]["nivel"] == "atencao"


def test_alerta_de_preventiva_atrasada(logado, base):
    vencida = (data_de_hoje() - timedelta(days=200)).isoformat()
    logado.put(f"/api/veiculos/{base['veiculo']['id']}",
               json={"data_ultima_preventiva": vencida, "intervalo_preventiva_dias": 90})
    alertas = logado.get("/api/painel/alertas").get_json()
    prev = [a for a in alertas if a["categoria"] == "Preventiva"]
    assert prev and prev[0]["nivel"] == "critico"


def test_alerta_de_pneu_no_limite(logado, base):
    logado.post("/api/pneus", json={"numero_fogo": "P100", "sulco_mm": 3.0,
                                    "veiculo_id": base["veiculo"]["id"], "status": "Em uso"})
    alertas = logado.get("/api/painel/alertas").get_json()
    pneus = [a for a in alertas if a["categoria"] == "Pneus"]
    assert pneus and pneus[0]["nivel"] == "critico"


def test_alerta_de_estoque_minimo(logado, base):
    logado.post("/api/movimentos", json={"peca_id": base["peca"]["id"],
                                         "tipo": "ajuste", "quantidade": 2})
    alertas = logado.get("/api/painel/alertas").get_json()
    assert any(a["categoria"] == "Estoque" for a in alertas)


def test_alerta_de_orcamento_estourado(logado, base):
    vid = base["veiculo"]["id"]
    logado.put(f"/api/veiculos/{vid}", json={"orcamento_mensal": 100})
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 100100,
                                             "litros": 100, "valor_litro": 6})
    alertas = logado.get("/api/painel/alertas").get_json()
    assert any(a["categoria"] == "Orçamento" and a["nivel"] == "critico" for a in alertas)


def test_alerta_de_falhas_recorrentes(logado, base):
    for _ in range(3):
        logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"],
                                         "tipo": "Corretiva", "grupo": "Elétrica"})
    alertas = logado.get("/api/painel/alertas").get_json()
    assert any(a["categoria"] == "Recorrência" for a in alertas)


def test_frota_em_dia_nao_gera_alerta(logado):
    logado.post("/api/veiculos", json={"prefixo": "FR-500", "placa": "OKA1B22",
                                       "hodometro": 1000, "km_ultima_troca_oleo": 1000,
                                       "intervalo_troca_oleo": 10000,
                                       "data_ultima_preventiva": data_de_hoje().isoformat()})
    assert logado.get("/api/painel/alertas").get_json() == []


RELATORIOS = ["abastecimentos", "manutencoes", "custos", "veiculos", "pneus",
              "estoque", "movimentos"]


@pytest.mark.parametrize("relatorio", RELATORIOS)
@pytest.mark.parametrize("formato,tipo", [
    ("pdf", "application/pdf"),
    ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("csv", "text/csv"),
])
def test_exportacao_de_relatorios(logado, movimentado, relatorio, formato, tipo):
    r = logado.get(f"/relatorios/{relatorio}.{formato}")
    assert r.status_code == 200
    assert tipo in r.headers["Content-Type"]
    assert len(r.data) > 100, "o arquivo veio vazio"
    assert "attachment" in r.headers["Content-Disposition"]
    assert f"sgmf_{relatorio}" in r.headers["Content-Disposition"]


def test_relatorio_respeita_o_filtro_de_veiculo(logado, movimentado, base):
    conteudo = logado.get(
        f"/relatorios/abastecimentos.csv?veiculo_id={base['veiculo']['id']}"
    ).data.decode("utf-8-sig")
    assert "FR-001" in conteudo
    assert conteudo.count("\r\n") >= 2


def test_relatorio_sem_dados_no_periodo(logado):
    r = logado.get("/relatorios/abastecimentos.pdf?inicio=2020-01-01&fim=2020-01-31")
    assert r.status_code == 200
    assert len(r.data) > 500


def test_backup_traz_todas_as_tabelas(logado, movimentado):
    pacote = logado.get("/relatorios/backup.json").get_json()
    for chave in ["veiculos", "motoristas", "fornecedores", "ordens", "abastecimentos",
                  "pneus", "pecas", "movimentos", "orcamentos", "usuarios"]:
        assert chave in pacote
    assert len(pacote["abastecimentos"]) == 2


def test_relatorio_exige_sessao(cliente):
    assert cliente.get("/relatorios/veiculos.pdf").status_code == 401
