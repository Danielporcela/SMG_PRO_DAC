"""OS sem nenhuma peça lançada pode ser finalizada mesmo com custo zerado."""
from types import SimpleNamespace

import pytest

from routes.api import _verificar_valor_os
from services.crud import ErroNegocio


def test_os_sem_pecas_finaliza_com_custo_zerado(logado, base):
    os_criada = logado.post("/api/ordens", json={"veiculo_id": base["veiculo"]["id"]}).get_json()
    r = logado.put(f"/api/ordens/{os_criada['id']}", json={"status": "Finalizada"})
    assert r.status_code == 200
    assert r.get_json()["status"] == "Finalizada"


def _os(itens, custo_total=0):
    return SimpleNamespace(status="Finalizada", custo_total=custo_total, itens=itens)


def test_os_com_peca_e_custo_zerado_continua_bloqueada():
    with pytest.raises(ErroNegocio):
        _verificar_valor_os(_os([SimpleNamespace(eh_peca=True)]))


def test_os_so_com_servico_de_valor_zero_pode_finalizar():
    _verificar_valor_os(_os([SimpleNamespace(eh_peca=False)]))


def test_os_com_peca_e_custo_maior_que_zero_finaliza():
    _verificar_valor_os(_os([SimpleNamespace(eh_peca=True)], custo_total=50))
