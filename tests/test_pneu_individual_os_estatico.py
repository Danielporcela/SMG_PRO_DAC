from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_instalacao_exige_pneu_cadastrado_em_estoque():
    fonte = (ROOT / "services" / "correcoes_os.py").read_text(encoding="utf-8")
    assert "não está cadastrado no sistema" in fonte
    assert 'pneu_novo.status != "Estoque"' in fonte
    assert "Pneu(numero_fogo=" not in fonte

def test_item_os_vincula_numero_de_fogo():
    modelos = (ROOT / "models.py").read_text(encoding="utf-8")
    assert 'pneu_id = db.Column(db.Integer, db.ForeignKey("pneus.id")' in modelos

def test_modal_seleciona_pneu_do_estoque():
    rota = (ROOT / "routes" / "correcao_os.py").read_text(encoding="utf-8")
    assert 'Pneu.query.filter_by(status="Estoque")' in rota
    assert "pneus_estoque" in rota
    assert "Selecione o pneu cadastrado" in rota


def test_mapa_respeita_quantidade_de_eixos_traseiros():
    fonte = (ROOT / "services" / "correcoes_os.py").read_text(encoding="utf-8")
    assert "eixos_traseiros" in fonte
    assert "eixos_traseiros >= 2" in fonte
    tela = (ROOT / "templates" / "veiculos.html").read_text(encoding="utf-8")
    assert "eixos_traseiros" in tela
