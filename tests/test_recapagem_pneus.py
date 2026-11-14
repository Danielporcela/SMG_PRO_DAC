"""Ciclo do pneu: retirado -> recapagem (NF com nº de fogo) -> estoque / descarte."""
from extensions import db
from models import Pneu


def _pneu(app, fogo, status="Retirado", vida="Novo"):
    with app.app_context():
        p = Pneu(numero_fogo=fogo, status=status, vida=vida, marca="Teste")
        db.session.add(p)
        db.session.commit()
        return p.id


def test_nf_de_retorno_volta_ao_estoque_com_numero_da_recapagem(app, logado):
    _pneu(app, "F100")
    _pneu(app, "F101", vida="1ª recapagem")

    r = logado.post("/api/pneus-retirados/enviar-recapagem",
                    json={"pneu_ids": [p["id"] for p in logado.get("/api/pneus-retirados").get_json()]})
    assert r.status_code == 200

    r = logado.post("/api/recapagem/notas", json={
        "numero": "1234", "serie": "1",
        "itens": [{"numero_fogo": "F100", "resultado": "Recapado", "valor": "450,00"},
                  {"numero_fogo": "F101", "resultado": "Recapado"}]})
    assert r.status_code == 201

    with app.app_context():
        a = Pneu.query.filter_by(numero_fogo="F100").one()
        b = Pneu.query.filter_by(numero_fogo="F101").one()
        assert (a.status, a.vida) == ("Estoque", "1ª recapagem")
        assert (b.status, b.vida) == ("Estoque", "2ª recapagem")
    assert logado.get("/api/pneus-retirados").get_json() == []


def test_pneu_recusado_na_recapagem_vai_para_descarte(app, logado):
    _pneu(app, "F200", vida="2ª recapagem")
    r = logado.post("/api/recapagem/notas", json={
        "numero": "55", "itens": [{"numero_fogo": "F200", "resultado": "Descartado",
                                   "motivo": "Carcaça trincada"}]})
    assert r.status_code == 201
    lista = logado.get("/api/pneus-descartados").get_json()
    assert [l["numero_fogo"] for l in lista] == ["F200"]
    assert lista[0]["descarte_nota"] == "NF 55"
    assert lista[0]["descarte_motivo"] == "Carcaça trincada"


def test_nf_rejeita_pneu_que_nao_foi_retirado(app, logado):
    _pneu(app, "F300", status="Em uso")
    r = logado.post("/api/recapagem/notas", json={
        "numero": "9", "itens": [{"numero_fogo": "F300", "resultado": "Recapado"}]})
    assert r.status_code == 400
    with app.app_context():
        assert Pneu.query.filter_by(numero_fogo="F300").one().status == "Em uso"


def test_descarte_direto_da_lista_de_retirados(app, logado):
    pid = _pneu(app, "F400")
    r = logado.post(f"/api/pneus-retirados/{pid}/descartar", json={"motivo": "Estourou"})
    assert r.status_code == 200
    assert logado.get("/api/pneus-descartados").get_json()[0]["numero_fogo"] == "F400"
    assert logado.get(f"/api/pneus/{pid}/ciclo").get_json()["eventos"][-1]["evento"] == "Descarte"
