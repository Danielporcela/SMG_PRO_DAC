"""Fuso horário, perfil de consulta, auditoria e restauração de backup."""
import io
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from services.tempo import FUSO, agora, hoje


# ------------------------------------------------------------- fuso horário
def test_data_do_sistema_usa_o_fuso_da_empresa():
    esperado = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    assert hoje() == esperado


def test_hora_do_sistema_tem_fuso_definido():
    momento = agora()
    assert momento.tzinfo is not None
    assert str(FUSO) == "America/Sao_Paulo"


def test_lancamento_recebe_a_data_local(logado, base):
    r = logado.post("/api/abastecimentos", json={"veiculo_id": base["veiculo"]["id"],
                                                 "km_atual": 100300, "litros": 50,
                                                 "valor_litro": 6}).get_json()
    assert r["data"] == hoje().isoformat()


# --------------------------------------------------------- perfil consulta
@pytest.fixture()
def consulta(logado, cliente):
    """Cliente autenticado com um usuário de perfil somente leitura."""
    logado.post("/api/usuarios", json={"nome": "Fiscal", "email": "fiscal@teste.local",
                                       "perfil": "consulta", "senha": "fiscal123"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "fiscal@teste.local", "senha": "fiscal123"})
    return cliente


LISTAS = ["veiculos", "motoristas", "fornecedores", "ordens", "abastecimentos",
          "pneus", "pecas", "orcamentos", "movimentos"]


@pytest.mark.parametrize("recurso", LISTAS)
def test_consulta_pode_ver_tudo(consulta, recurso):
    assert consulta.get(f"/api/{recurso}").status_code == 200


def test_consulta_ve_paineis_e_relatorios(consulta):
    assert consulta.get("/api/painel/resumo").status_code == 200
    assert consulta.get("/api/painel/alertas").status_code == 200
    assert consulta.get("/relatorios/veiculos.pdf").status_code == 200


def test_consulta_nao_cria(consulta):
    r = consulta.post("/api/veiculos", json={"prefixo": "FR-777", "placa": "AAA1B22"})
    assert r.status_code == 403
    assert "perfil" in r.get_json()["erro"]


def test_consulta_nao_edita_nem_exclui(logado, cliente, base):
    vid = base["veiculo"]["id"]
    logado.post("/api/usuarios", json={"nome": "Fiscal", "email": "f2@teste.local",
                                       "perfil": "consulta", "senha": "fiscal123"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "f2@teste.local", "senha": "fiscal123"})
    assert cliente.put(f"/api/veiculos/{vid}", json={"setor": "X"}).status_code == 403
    assert cliente.delete(f"/api/veiculos/{vid}").status_code == 403


def test_consulta_nao_movimenta_estoque_nem_lanca_itens(logado, cliente, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    logado.post("/api/usuarios", json={"nome": "Fiscal", "email": "f3@teste.local",
                                       "perfil": "consulta", "senha": "fiscal123"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "f3@teste.local", "senha": "fiscal123"})

    assert cliente.post("/api/movimentos", json={"peca_id": base["peca"]["id"],
                                                 "tipo": "entrada",
                                                 "quantidade": 5}).status_code == 403
    assert cliente.post(f"/api/ordens/{os_criada['id']}/itens",
                        json={"descricao": "Teste"}).status_code == 403


def test_consulta_troca_a_propria_senha(consulta):
    r = consulta.post("/api/trocar-senha", json={"atual": "fiscal123", "nova": "outrasenha"})
    assert r.status_code == 200


def test_operador_continua_lancando(logado, cliente, base):
    logado.post("/api/usuarios", json={"nome": "Operador", "email": "op2@teste.local",
                                       "perfil": "operador", "senha": "operador123"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "op2@teste.local", "senha": "operador123"})
    r = cliente.post("/api/veiculos", json={"prefixo": "FR-800", "placa": "OPE1R22"})
    assert r.status_code == 201


# ---------------------------------------------------------------- auditoria
def test_auditoria_registra_as_acoes(logado, base):
    logado.put(f"/api/veiculos/{base['veiculo']['id']}", json={"setor": "Obras"})
    logs = logado.get("/api/logs").get_json()
    acoes = {(registro["acao"], registro["entidade"]) for registro in logs}
    assert ("criar", "veiculos") in acoes
    assert ("editar", "veiculos") in acoes
    assert logs[0]["usuario"] == "Administrador"


def test_auditoria_filtra_por_modulo(logado, base):
    logs = logado.get("/api/logs?entidade=pecas").get_json()
    assert logs and all(registro["entidade"] == "pecas" for registro in logs)


def test_auditoria_e_so_do_administrador(logado, cliente):
    logado.post("/api/usuarios", json={"nome": "Operador", "email": "op3@teste.local",
                                       "perfil": "operador", "senha": "operador123"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "op3@teste.local", "senha": "operador123"})
    assert cliente.get("/api/logs").status_code == 403


def test_pagina_de_auditoria_abre(logado):
    assert logado.get("/auditoria").status_code == 200


# ------------------------------------------------------- restaurar backup
def _enviar_backup(cliente, pacote):
    arquivo = io.BytesIO(json.dumps(pacote).encode("utf-8"))
    return cliente.post("/relatorios/restaurar",
                        data={"arquivo": (arquivo, "backup.json")},
                        content_type="multipart/form-data")


def test_backup_e_restauracao_devolvem_os_dados(logado, base):
    vid = base["veiculo"]["id"]
    logado.post("/api/abastecimentos", json={"veiculo_id": vid, "km_atual": 100400,
                                             "litros": 80, "valor_litro": 6})
    os_criada = logado.post("/api/ordens", json={"veiculo_id": vid,
                                                 "custo_mao_obra": 250}).get_json()
    logado.post(f"/api/ordens/{os_criada['id']}/itens",
                json={"peca_id": base["peca"]["id"], "quantidade": 2})
    pacote = logado.get("/relatorios/backup.json").get_json()

    # apaga tudo o que dá para apagar e confere que sumiu
    logado.delete(f"/api/ordens/{os_criada['id']}")
    assert logado.get("/api/ordens").get_json() == []

    resposta = _enviar_backup(logado, pacote)
    assert resposta.status_code == 200
    resumo = resposta.get_json()["resumo"]
    assert resumo["veiculos"] == 1
    assert resumo["ordens"] == 1
    assert resumo["itens_os"] == 1

    ordens = logado.get("/api/ordens").get_json()
    assert len(ordens) == 1
    assert ordens[0]["custo_total"] == 350.0     # 2 peças x 50 + 250
    assert len(logado.get("/api/abastecimentos").get_json()) == 1
    assert logado.get("/api/veiculos").get_json()[0]["placa"] == "ABC1D23"


def test_restauracao_nao_mexe_nos_usuarios(logado, cliente, base):
    pacote = logado.get("/relatorios/backup.json").get_json()
    logado.post("/api/usuarios", json={"nome": "Novo", "email": "novo@teste.local",
                                       "senha": "novo123456"})
    _enviar_backup(logado, pacote)
    logado.get("/logout")
    assert cliente.post("/login", json={"email": "novo@teste.local",
                                        "senha": "novo123456"}).status_code == 200


def test_restauracao_recusa_arquivo_invalido(logado):
    arquivo = io.BytesIO(b"isto nao e json")
    r = logado.post("/relatorios/restaurar",
                    data={"arquivo": (arquivo, "qualquer.json")},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "JSON" in r.get_json()["erro"]


def test_restauracao_recusa_json_de_outro_sistema(logado):
    r = _enviar_backup(logado, {"clientes": [], "produtos": []})
    assert r.status_code == 400
    assert "backup do SGMF" in r.get_json()["erro"]


def test_restauracao_sem_arquivo(logado):
    r = logado.post("/relatorios/restaurar", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_restauracao_e_so_do_administrador(logado, cliente, base):
    pacote = logado.get("/relatorios/backup.json").get_json()
    logado.post("/api/usuarios", json={"nome": "Operador", "email": "op4@teste.local",
                                       "perfil": "operador", "senha": "operador123"})
    logado.get("/logout")
    cliente.post("/login", json={"email": "op4@teste.local", "senha": "operador123"})
    assert _enviar_backup(cliente, pacote).status_code == 403


def test_restauracao_falha_sem_alterar_o_banco(logado, base):
    pacote = logado.get("/relatorios/backup.json").get_json()
    pacote["veiculos"].append({"id": 2, "prefixo": "FR-002", "placa": "ABC1D23"})  # placa repetida
    resposta = _enviar_backup(logado, pacote)
    assert resposta.status_code == 400
    veiculos = logado.get("/api/veiculos").get_json()
    assert len(veiculos) == 1, "o banco tinha que continuar como estava"
