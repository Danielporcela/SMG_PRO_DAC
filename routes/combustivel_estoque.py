"""NF de combustível, estoque físico e kardex do módulo Abastecimentos."""
from datetime import date

from flask import Blueprint, jsonify, request

from extensions import db
from models import NotaFiscalCombustivel
from services.crud import ErroNegocio, editar_tela, registrar_log, visualizar_tela
from services.estoque_combustivel import (ativar_controle, movimentacoes,
                                          recalcular_estoque_combustivel,
                                          recalcular_todos_combustiveis,
                                          resumo_geral)

bp_combustivel_estoque = Blueprint("combustivel_estoque", __name__, url_prefix="/api")


def _data(valor, nome="data", obrigatoria=False):
    if not valor:
        if obrigatoria:
            raise ErroNegocio(f"Informe {nome}.")
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ErroNegocio(f"{nome.capitalize()} inválida.")


def _float(valor, nome):
    try:
        return float(str(valor).replace(".", "").replace(",", ".")) if isinstance(valor, str) and "," in valor else float(valor or 0)
    except (TypeError, ValueError):
        raise ErroNegocio(f"{nome} inválido.")


def _aplicar(nota, dados):
    nota.numero_nf = (dados.get("numero_nf") or "").strip()
    if not nota.numero_nf:
        raise ErroNegocio("Informe o número da nota fiscal.")
    nota.data = _data(dados.get("data"), "data da NF", True)
    nota.data_entrada = _data(dados.get("data_entrada"), "data de entrada no estoque") or nota.data
    nota.fornecedor_id = int(dados["fornecedor_id"]) if dados.get("fornecedor_id") else None
    nota.combustivel = (dados.get("combustivel") or "Diesel S10").strip()
    nota.litros = _float(dados.get("litros"), "Litros")
    nota.valor_litro = _float(dados.get("valor_litro"), "Valor por litro")
    nota.valor_total = _float(dados.get("valor_total"), "Valor total")
    if nota.litros <= 0:
        raise ErroNegocio("A quantidade da NF deve ser maior que zero.")
    if nota.valor_total <= 0 and nota.valor_litro > 0:
        nota.valor_total = round(nota.litros * nota.valor_litro, 2)
    elif nota.valor_litro <= 0 and nota.valor_total > 0:
        nota.valor_litro = round(nota.valor_total / nota.litros, 4)
    elif nota.valor_total > 0 and nota.valor_litro > 0:
        # O total fiscal prevalece; o unitário é recalculado para manter coerência.
        nota.valor_litro = round(nota.valor_total / nota.litros, 4)
    if nota.valor_total <= 0:
        raise ErroNegocio("Informe o valor da nota fiscal.")
    nota.vencimento = _data(dados.get("vencimento"), "vencimento")
    nota.observacao = (dados.get("observacao") or "").strip() or None


@bp_combustivel_estoque.get("/notas-combustivel")
@visualizar_tela("combustivel")
def listar_notas():
    q = NotaFiscalCombustivel.query
    inicio = request.args.get("inicio")
    fim = request.args.get("fim")
    if inicio:
        q = q.filter(NotaFiscalCombustivel.data >= _data(inicio, "data inicial"))
    if fim:
        q = q.filter(NotaFiscalCombustivel.data <= _data(fim, "data final"))
    notas = q.order_by(NotaFiscalCombustivel.data.desc(), NotaFiscalCombustivel.id.desc()).all()
    return jsonify([n.to_dict() for n in notas])


@bp_combustivel_estoque.post("/notas-combustivel")
@editar_tela("combustivel")
def criar_nota():
    dados = request.get_json(silent=True) or {}
    nota = NotaFiscalCombustivel()
    try:
        _aplicar(nota, dados)
        db.session.add(nota)
        db.session.flush()
        ativar_controle(nota.combustivel, nota.data_entrada or nota.data)
        recalcular_estoque_combustivel(nota.combustivel)
        registrar_log("criar", "notas_combustivel", nota.id, f"NF {nota.numero_nf}")
        db.session.commit()
        return jsonify(nota.to_dict()), 201
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível salvar a NF ({e.__class__.__name__})."}), 400


@bp_combustivel_estoque.put("/notas-combustivel/<int:nota_id>")
@editar_tela("combustivel")
def editar_nota(nota_id):
    nota = db.get_or_404(NotaFiscalCombustivel, nota_id)
    antigo = nota.combustivel
    try:
        _aplicar(nota, request.get_json(silent=True) or {})
        db.session.flush()
        ativar_controle(nota.combustivel, nota.data_entrada or nota.data)
        recalcular_estoque_combustivel(nota.combustivel)
        if antigo != nota.combustivel:
            recalcular_estoque_combustivel(antigo)
        registrar_log("editar", "notas_combustivel", nota.id, f"NF {nota.numero_nf}")
        db.session.commit()
        return jsonify(nota.to_dict())
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível editar a NF ({e.__class__.__name__})."}), 400


@bp_combustivel_estoque.delete("/notas-combustivel/<int:nota_id>")
@editar_tela("combustivel")
def excluir_nota(nota_id):
    nota = db.get_or_404(NotaFiscalCombustivel, nota_id)
    combustivel = nota.combustivel
    numero = nota.numero_nf
    try:
        db.session.delete(nota)
        db.session.flush()
        # Não permite apagar uma entrada se isso fizer qualquer saída histórica ficar sem saldo.
        recalcular_estoque_combustivel(combustivel)
        registrar_log("excluir", "notas_combustivel", nota_id, f"NF {numero}")
        db.session.commit()
        return jsonify({"ok": True})
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível excluir a NF ({e.__class__.__name__})."}), 400


@bp_combustivel_estoque.post("/combustivel/reconciliar-estoque")
@editar_tela("combustivel")
def reconciliar_estoque():
    """Reprocessa NFs e abastecimentos já existentes sem apagar histórico."""
    try:
        resultados = recalcular_todos_combustiveis()
        registrar_log("reconciliar", "estoque_combustivel", None,
                      f"{len(resultados)} combustível(is) recalculado(s)")
        db.session.commit()
        return jsonify({"ok": True, "itens": resultados, "resumo": resumo_geral()})
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível reconciliar o estoque ({e.__class__.__name__})."}), 400


@bp_combustivel_estoque.get("/combustivel/estoque-resumo")
@visualizar_tela("combustivel")
def estoque_resumo():
    try:
        # Consulta: não trava a tela por inconsistência antiga; devolve "alertas".
        dados = resumo_geral(estrito=False)
        db.session.rollback()  # GET não persiste eventual recálculo de custo.
        return jsonify(dados)
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400


@bp_combustivel_estoque.get("/combustivel/movimentacoes")
@visualizar_tela("combustivel")
def listar_movimentacoes():
    try:
        inicio = _data(request.args.get("inicio"), "data inicial") if request.args.get("inicio") else None
        fim = _data(request.args.get("fim"), "data final") if request.args.get("fim") else None
        linhas = movimentacoes(inicio, fim, estrito=False)
        db.session.rollback()
        return jsonify(linhas)
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
