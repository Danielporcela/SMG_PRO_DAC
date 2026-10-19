"""Índice de mecânicos baseado exclusivamente no número de OS finalizadas."""
from datetime import date, timedelta, time
from models import OrdemServico
from extensions import db
from services import indicadores


def test_ranking_ordens_finalizadas_sem_peso_de_horas(app, base):
    hoje = date.today()
    vid = base["veiculo"]["id"]
    with app.app_context():
        # Duas OS curtas de Ana x uma OS longa de Bruno:
        # Ana precisa liderar, mesmo tendo MENOS horas totais.
        for nome, horas, situacao in (
            ("ANA", 1, "Finalizada"),
            ("Ana", 2, "Finalizada"),
            ("Bruno", 8, "Finalizada"),
            ("Bruno", 9, "Aberta"),
        ):
            ordem = OrdemServico(veiculo_id=vid, mecanico=nome,
                status=situacao, data_abertura=hoje,
                data_fechamento=hoje if situacao == "Finalizada" else None,
                hora_inicio=time(8, 0), hora_fim=time(8 + horas, 0))
            db.session.add(ordem)
        db.session.commit()
        dados = indicadores.horas_por_mecanico(hoje.isoformat(), hoje.isoformat())
        assert [p["mecanico"] for p in dados] == ["Ana", "Bruno"]
        assert [p["os"] for p in dados] == [2, 1]
        assert dados[0]["horas"] == 3
        assert dados[1]["horas"] == 8
        assert indicadores.rankings(hoje.isoformat(), hoje.isoformat())["mecanicos_mais_os"] == dados


def test_periodo_usa_data_fechamento_e_legado_sem_data(app, base):
    hoje = date.today()
    ontem = hoje - timedelta(days=1)
    vid = base["veiculo"]["id"]
    with app.app_context():
        db.session.add_all([
            OrdemServico(veiculo_id=vid, mecanico="Edson", status="Finalizada",
                         data_abertura=ontem, data_fechamento=hoje),
            OrdemServico(veiculo_id=vid, mecanico="Gilmar", status="Finalizada",
                         data_abertura=ontem, data_fechamento=None),
        ])
        db.session.commit()
        periodo = indicadores.horas_por_mecanico(hoje.isoformat(), hoje.isoformat())
        assert [(m["mecanico"], m["os"]) for m in periodo] == [("Edson", 1)]
        periodo = indicadores.horas_por_mecanico(ontem.isoformat(), ontem.isoformat())
        assert [(m["mecanico"], m["os"]) for m in periodo] == [("Gilmar", 1)]


def test_desempate_e_por_nome_nao_por_horas(app, base):
    hoje = date.today()
    vid = base["veiculo"]["id"]
    with app.app_context():
        db.session.add_all([
            OrdemServico(veiculo_id=vid, mecanico="Zeca", status="Finalizada",
                         data_abertura=hoje, data_fechamento=hoje,
                         hora_inicio=time(8, 0), hora_fim=time(18, 0)),
            OrdemServico(veiculo_id=vid, mecanico="Alan", status="Finalizada",
                         data_abertura=hoje, data_fechamento=hoje,
                         hora_inicio=time(8, 0), hora_fim=time(9, 0)),
        ])
        db.session.commit()
        assert [m["mecanico"] for m in indicadores.horas_por_mecanico(
            hoje.isoformat(), hoje.isoformat())] == ["Alan", "Zeca"]
