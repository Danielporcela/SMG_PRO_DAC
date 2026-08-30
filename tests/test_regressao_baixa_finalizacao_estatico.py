"""Regressão estrutural da baixa de estoque ao finalizar uma OS.

Este arquivo usa apenas a biblioteca padrão para poder validar a regra mesmo
quando as dependências web do projeto não estão instaladas no ambiente local.
A suíte funcional em test_regras.py continua sendo a validação principal em
um ambiente com as dependências do requirements.txt disponíveis.
"""
import ast
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def _funcao(caminho, nome):
    arvore = ast.parse((RAIZ / caminho).read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)) and no.name == nome:
            return no
    raise AssertionError(f"Função {nome} não encontrada em {caminho}")


def _chamadas(funcao):
    nomes = []
    for no in ast.walk(funcao):
        if isinstance(no, ast.Call):
            alvo = no.func
            if isinstance(alvo, ast.Name):
                nomes.append(alvo.id)
            elif isinstance(alvo, ast.Attribute):
                nomes.append(alvo.attr)
    return nomes


def test_finalizacao_da_os_dispara_baixa_dos_itens():
    funcao = _funcao("routes/api.py", "_depois_os")
    chamadas = _chamadas(funcao)
    assert "baixar_item_os" in chamadas, (
        "Ao salvar uma OS Finalizada, routes/api.py precisa chamar baixar_item_os "
        "para processar as peças pendentes."
    )


def test_baixa_do_item_continua_idempotente():
    funcao = _funcao("services/calculos.py", "baixar_item_os")
    fonte = ast.unparse(funcao)
    assert "not item.baixado_estoque" in fonte
    assert "movimentar_estoque" in _chamadas(funcao)


def test_crud_faz_rollback_quando_regra_de_negocio_falha():
    funcao = _funcao("services/crud.py", "registrar_crud")
    fonte = ast.unparse(funcao)
    assert "db.session.rollback()" in fonte
    assert "ErroNegocio" in fonte
