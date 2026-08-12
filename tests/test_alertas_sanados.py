from datetime import timedelta

import pytest
from flask import Flask

from extensions import db
from models import Motorista, OrdemServico, Peca, Pneu, Veiculo
from services.alertas import listar_alertas_ativos, sincronizar_estados
from services.tempo import hoje


@pytest.fixture()
def app():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SULCO_MINIMO_MM=4.0,
        KM_AVISO_TROCA_OLEO=500,
        ALERTA_PREVENTIVA_DIAS=30,
        ALERTA_CNH_DIAS=30,
        DESVIO_CONSUMO_ALERTA=0.15,
    )
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


def chaves():
    return {a["chave"] for a in listar_alertas_ativos()}


def test_estoque_some_quando_reposto(app):
    with app.app_context():
        p = Peca(codigo="TESTE", descricao="Peça teste", quantidade=2, estoque_minimo=5)
        db.session.add(p)
        db.session.commit()
        assert f"estoque:peca:{p.id}" in chaves()
        sincronizar_estados()

        p.quantidade = 10
        db.session.commit()
        estado = sincronizar_estados()
        assert f"estoque:peca:{p.id}" not in chaves()
        assert any(a["chave"] == f"estoque:peca:{p.id}" for a in estado["sanados"])


def test_pneu_some_quando_condicao_e_corrigida(app):
    with app.app_context():
        v = Veiculo(prefixo="V1", placa="AAA1A11", hodometro=1000,
                    km_ultima_troca_oleo=1000, intervalo_troca_oleo=10000,
                    data_ultima_preventiva=hoje(), intervalo_preventiva_dias=90)
        db.session.add(v)
        db.session.flush()
        p = Pneu(numero_fogo="P1", veiculo_id=v.id, sulco_mm=3.0, status="Em uso")
        db.session.add(p)
        db.session.commit()
        assert f"pneu:{p.id}" in chaves()
        sincronizar_estados()

        p.status = "Estoque"
        db.session.commit()
        estado = sincronizar_estados()
        assert f"pneu:{p.id}" not in chaves()
        assert any(a["chave"] == f"pneu:{p.id}" for a in estado["sanados"])


def test_cnh_some_apos_renovacao(app):
    with app.app_context():
        m = Motorista(nome="Motorista", validade_cnh=hoje() + timedelta(days=5), ativo=True)
        db.session.add(m)
        db.session.commit()
        assert f"cnh:motorista:{m.id}" in chaves()
        sincronizar_estados()

        m.validade_cnh = hoje() + timedelta(days=365)
        db.session.commit()
        estado = sincronizar_estados()
        assert f"cnh:motorista:{m.id}" not in chaves()
        assert any(a["chave"] == f"cnh:motorista:{m.id}" for a in estado["sanados"])


def test_finalizar_preventiva_atualiza_marcos_e_limpa_alertas(app):
    with app.app_context():
        v = Veiculo(
            prefixo="V2", placa="BBB2B22", hodometro=10000,
            km_ultima_troca_oleo=0, intervalo_troca_oleo=10000,
            data_ultima_preventiva=hoje() - timedelta(days=120),
            intervalo_preventiva_dias=90, situacao="Em manutenção", ativo=True,
        )
        db.session.add(v)
        db.session.commit()
        assert f"oleo:veiculo:{v.id}" in chaves()
        assert f"preventiva:veiculo:{v.id}" in chaves()
        sincronizar_estados()

        os_obj = OrdemServico(
            numero="OS100", veiculo_id=v.id, tipo="Preventiva", grupo="Motor",
            status="Aberta", km_veiculo=10000,
            descricao="Revisão preventiva com troca de óleo e filtros.",
        )
        db.session.add(os_obj)
        db.session.commit()

        os_obj.status = "Finalizada"
        db.session.commit()
        db.session.refresh(v)

        assert v.data_ultima_preventiva == hoje()
        assert v.km_ultima_troca_oleo == 10000
        assert v.situacao == "Disponível"
        assert os_obj.data_fechamento == hoje()

        estado = sincronizar_estados()
        atuais = chaves()
        assert f"oleo:veiculo:{v.id}" not in atuais
        assert f"preventiva:veiculo:{v.id}" not in atuais
        sanadas = {a["chave"] for a in estado["sanados"]}
        assert f"oleo:veiculo:{v.id}" in sanadas
        assert f"preventiva:veiculo:{v.id}" in sanadas
