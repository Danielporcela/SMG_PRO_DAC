from pathlib import Path


def test_pacote_nao_inclui_banco_ou_seed():
    raiz = Path(__file__).resolve().parents[1]
    nomes = {p.name for p in raiz.rglob('*') if p.is_file()}
    assert 'sgmf.db' not in nomes
    assert 'seed.py' not in nomes


def test_posicoes_presentes():
    texto = (Path(__file__).resolve().parents[1] / 'services' / 'correcoes_os.py').read_text(encoding='utf-8')
    for nome in ('Dianteiro Esquerdo', 'Dianteiro Direito', 'Traseiro Esquerdo Externo', 'Traseiro Esquerdo Interno', 'Traseiro Direito Externo', 'Traseiro Direito Interno'):
        assert nome in texto
