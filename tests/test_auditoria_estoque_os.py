from extensions import db
from models import ItemOS, OrdemServico, Peca
from services.tempo import hoje


def criar_pendencia_historica(app, base, quantidade=3):
    with app.app_context():
        ordem = OrdemServico(
            numero=f"HIST{quantidade:03d}", data_abertura=hoje(), data_fechamento=hoje(),
            veiculo_id=base["veiculo"]["id"], status="Finalizada")
        db.session.add(ordem)
        db.session.flush()
        item = ItemOS(
            ordem_servico_id=ordem.id, peca_id=base["peca"]["id"],
            descricao="Filtro de óleo", quantidade=quantidade,
            valor_unitario=50, baixado_estoque=False)
        db.session.add(item)
        db.session.commit()
        return ordem.id, item.id


def test_lista_os_finalizadas_com_baixa_pendente(logado, app, base):
    os_id, _ = criar_pendencia_historica(app, base, 3)

    resposta = logado.get("/api/auditoria_estoque_os")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["resumo"]["total_os"] == 1
    assert dados["resumo"]["podem_regularizar"] == 1
    assert dados["ordens"][0]["id"] == os_id
    assert dados["ordens"][0]["pode_regularizar"] is True
    assert dados["ordens"][0]["itens"][0]["estoque_atual"] == 20


def test_regularizacao_baixa_estoque_e_remove_pendencia(logado, app, base):
    os_id, item_id = criar_pendencia_historica(app, base, 3)

    resposta = logado.post(f"/api/auditoria_estoque_os/{os_id}/regularizar")
    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados["resumo"]["total_os"] == 0

    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 17
    detalhes = logado.get(f"/api/ordens/{os_id}/itens").get_json()
    item = next(i for i in detalhes["itens"] if i["id"] == item_id)
    assert item["baixado_estoque"] is True


def test_regularizacao_com_saldo_insuficiente_nao_altera_nada(logado, app, base):
    os_id, item_id = criar_pendencia_historica(app, base, 3)
    with app.app_context():
        peca = db.session.get(Peca, base["peca"]["id"])
        peca.quantidade = 2
        db.session.commit()

    resposta = logado.post(f"/api/auditoria_estoque_os/{os_id}/regularizar")
    assert resposta.status_code == 400
    assert "insuficiente" in resposta.get_json()["erro"].lower()
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 2
    detalhes = logado.get(f"/api/ordens/{os_id}/itens").get_json()
    item = next(i for i in detalhes["itens"] if i["id"] == item_id)
    assert item["baixado_estoque"] is False
    assert detalhes["status"] == "Finalizada"


def test_regularizacao_nao_pode_ser_repetida(logado, app, base):
    os_id, _ = criar_pendencia_historica(app, base, 3)
    primeira = logado.post(f"/api/auditoria_estoque_os/{os_id}/regularizar")
    segunda = logado.post(f"/api/auditoria_estoque_os/{os_id}/regularizar")

    assert primeira.status_code == 200
    assert segunda.status_code == 400
    assert logado.get(f"/api/pecas/{base['peca']['id']}").get_json()["quantidade"] == 17


def test_painel_mostra_quantidade_de_os_com_baixa_pendente(logado, app, base):
    criar_pendencia_historica(app, base, 3)
    resumo = logado.get("/api/painel/resumo").get_json()
    assert resumo["os_estoque_pendentes"] == 1
