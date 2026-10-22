"""Ferramentas dos caminhões (frota).

Onde lançar as ferramentas (pá, enxada, rastelo, garfo...) usadas em cada
veículo da frota. As ferramentas continuam cadastradas no ESTOQUE DE PEÇAS:
cada lançamento dá BAIXA direto nele, na mesma transação, e fica registrado
no histórico de movimentos do estoque (documento FERR-VEIC-<id>).

Regras:
- um lançamento pode ter várias ferramentas; se uma não tiver saldo, NADA é
  gravado (tudo ou nada);
- o custo é o custo médio da peça na data do lançamento e fica congelado;
- cancelar devolve a quantidade ao estoque (exclusão lógica, com histórico) e
  exige a senha de administrador, como toda exclusão do sistema (app.py);
- itens com rastreio individual por número de série (legado) não são aceitos
  aqui, porque a baixa por quantidade deixaria o serial "em estoque".
"""
import math
from collections import OrderedDict
from uuid import uuid4

from flask import Blueprint, g, jsonify, request, session
from sqlalchemy import text

from extensions import db
from models import MovimentoEstoque, Peca, PecaSerial, UsoFerramentaVeiculo, Veiculo
from routes.busca_pecas import combina, normalizar
from services.calculos import movimentar_estoque
from services.crud import ErroNegocio, editar_tela, registrar_log, visualizar_tela
from services.tempo import hoje, ler_data

bp_ferramentas_caminhoes = Blueprint(
    "ferramentas_caminhoes", __name__, url_prefix="/api/ferramentas-caminhoes")

TELA = "ferramentas_caminhoes"
LIMITE_PECAS = 60        # resultados por busca
LIMITE_LANCAMENTOS = 500  # linhas por listagem
MAX_ITENS = 50            # ferramentas por lançamento


def _frota_ativa():
    """Mesma frota do painel: veículos ativos, sem os setores antigos."""
    return Veiculo.query.filter(Veiculo.ativo.is_(True),
                                Veiculo.grupo_consumo_legado.isnot(True))


# ------------------------------------------------------------------ consultas
@bp_ferramentas_caminhoes.get("/veiculos")
@visualizar_tela(TELA)
def listar_veiculos():
    veiculos = _frota_ativa().order_by(Veiculo.prefixo).all()
    return jsonify([{"id": v.id, "prefixo": v.prefixo, "placa": v.placa_exibicao,
                     "tipo": v.tipo, "rotulo": v.rotulo} for v in veiculos])


@bp_ferramentas_caminhoes.get("/grupos")
@visualizar_tela(TELA)
def listar_grupos():
    """Grupos usados no estoque de peças (filtro da busca)."""
    return jsonify(sorted({gr for (gr,) in db.session.query(Peca.grupo).distinct().all() if gr}))


@bp_ferramentas_caminhoes.get("/pecas")
@visualizar_tela(TELA)
def buscar_pecas():
    """Pesquisa no estoque de peças (código, referência, nome, grupo).

    Somente leitura. Sem texto digitado devolve as primeiras peças do grupo
    escolhido, para a pessoa ver a lista e clicar.
    """
    termo = (request.args.get("q") or "").strip()
    grupo = (request.args.get("grupo") or "").strip()
    consulta = Peca.query
    if grupo:
        consulta = consulta.filter(Peca.grupo == grupo)
    termos = [normalizar(t) for t in termo.split() if t.strip()]
    encontradas = []
    for peca in consulta.order_by(Peca.descricao).all():
        if termos and not combina(peca, termos, "tudo"):
            continue
        encontradas.append(peca)
    return jsonify({
        "total": len(encontradas), "limite": LIMITE_PECAS,
        "pecas": [{"id": p.id, "codigo": p.codigo, "referencia": p.referencia,
                   "descricao": p.descricao, "grupo": p.grupo, "unidade": p.unidade,
                   "quantidade": p.quantidade or 0,
                   "custo_unitario": p.custo_unitario or 0}
                  for p in encontradas[:LIMITE_PECAS]],
    })


@bp_ferramentas_caminhoes.get("")
@visualizar_tela(TELA)
def listar_lancamentos():
    q = UsoFerramentaVeiculo.query
    inicio = ler_data(request.args.get("inicio"), "início do período")
    fim = ler_data(request.args.get("fim"), "fim do período")
    if inicio:
        q = q.filter(UsoFerramentaVeiculo.data >= inicio)
    if fim:
        q = q.filter(UsoFerramentaVeiculo.data <= fim)
    if request.args.get("veiculo_id", type=int):
        q = q.filter(UsoFerramentaVeiculo.veiculo_id == request.args.get("veiculo_id", type=int))
    if request.args.get("peca_id", type=int):
        q = q.filter(UsoFerramentaVeiculo.peca_id == request.args.get("peca_id", type=int))
    if request.args.get("incluir_cancelados") != "1":
        q = q.filter(UsoFerramentaVeiculo.data_cancelamento.is_(None))
    q = q.order_by(UsoFerramentaVeiculo.data.desc(), UsoFerramentaVeiculo.id.desc())
    return jsonify([u.to_dict() for u in q.limit(LIMITE_LANCAMENTOS).all()])


@bp_ferramentas_caminhoes.get("/resumo")
@visualizar_tela(TELA)
def resumo_por_frota():
    """Quanto cada veículo consumiu de ferramentas no período (sem cancelados)."""
    inicio = ler_data(request.args.get("inicio"), "início do período")
    fim = ler_data(request.args.get("fim"), "fim do período")
    q = UsoFerramentaVeiculo.query.filter(UsoFerramentaVeiculo.data_cancelamento.is_(None))
    if inicio:
        q = q.filter(UsoFerramentaVeiculo.data >= inicio)
    if fim:
        q = q.filter(UsoFerramentaVeiculo.data <= fim)
    por_veiculo = OrderedDict()
    total_valor = total_qtd = 0.0
    for u in q.order_by(UsoFerramentaVeiculo.veiculo_id).all():
        r = por_veiculo.setdefault(u.veiculo_id, {
            "veiculo_id": u.veiculo_id,
            "veiculo_nome": u.veiculo.rotulo if u.veiculo else "—",
            "lancamentos": 0, "quantidade": 0.0, "valor_total": 0.0})
        r["lancamentos"] += 1
        r["quantidade"] += u.quantidade or 0
        r["valor_total"] += u.valor_total
        total_qtd += u.quantidade or 0
        total_valor += u.valor_total
    linhas = sorted(por_veiculo.values(), key=lambda r: r["valor_total"], reverse=True)
    for r in linhas:
        r["quantidade"] = round(r["quantidade"], 2)
        r["valor_total"] = round(r["valor_total"], 2)
    return jsonify({"veiculos": linhas, "total_valor": round(total_valor, 2),
                    "total_quantidade": round(total_qtd, 2),
                    "total_lancamentos": sum(r["lancamentos"] for r in linhas)})


# --------------------------------------------------------------- lançamento
def _numero_positivo(valor, rotulo):
    try:
        numero = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        raise ErroNegocio(f"Quantidade inválida em {rotulo}.")
    if not math.isfinite(numero) or numero <= 0:
        raise ErroNegocio(f"Informe uma quantidade maior que zero em {rotulo}.")
    return numero


@bp_ferramentas_caminhoes.post("")
@editar_tela(TELA)
def lancar_ferramentas():
    """Lança as ferramentas usadas em um veículo e dá baixa no estoque de peças."""
    dados = request.get_json(silent=True) or {}
    try:
        veiculo = db.session.get(Veiculo, int(dados.get("veiculo_id") or 0))
        if not veiculo or veiculo.grupo_consumo_legado:
            raise ErroNegocio("Selecione o caminhão (veículo da frota).")
        if not veiculo.ativo:
            raise ErroNegocio(f"O veículo {veiculo.rotulo} está inativo.")

        data_lancamento = ler_data(dados.get("data"), "data do lançamento") or hoje()
        if data_lancamento > hoje():
            raise ErroNegocio("A data do lançamento não pode ser futura.")

        itens = dados.get("itens")
        if not isinstance(itens, list) or not itens:
            raise ErroNegocio("Adicione ao menos uma ferramenta ao lançamento.")
        if len(itens) > MAX_ITENS:
            raise ErroNegocio(f"Um lançamento aceita no máximo {MAX_ITENS} ferramentas.")

        # A mesma ferramenta repetida na lista vira uma linha só (soma).
        por_peca = OrderedDict()
        for item in itens:
            if not isinstance(item, dict):
                raise ErroNegocio("Item de ferramenta inválido.")
            try:
                peca_id = int(item.get("peca_id") or 0)
            except (TypeError, ValueError):
                raise ErroNegocio("Ferramenta inválida.")
            if not peca_id:
                raise ErroNegocio("Selecione a ferramenta em todas as linhas.")
            por_peca[peca_id] = por_peca.get(peca_id, 0) + _numero_positivo(
                item.get("quantidade"), f"a ferramenta #{peca_id}")

        responsavel = " ".join((dados.get("responsavel") or "").split())[:80] or None
        extra = (dados.get("observacao") or "").strip()[:120]
        usuario = session.get("usuario_nome") or "Sistema"

        criados = []
        for peca_id, quantidade in por_peca.items():
            peca = db.session.get(Peca, peca_id)
            if not peca:
                raise ErroNegocio("Uma das ferramentas não está mais cadastrada no estoque de peças.")
            if PecaSerial.query.filter_by(peca_id=peca.id).first() is not None:
                raise ErroNegocio(
                    f"{peca.codigo} · {peca.descricao} tem rastreio individual por número de "
                    "série. Esse item não pode ser lançado por quantidade aqui.")
            if quantidade > float(peca.quantidade or 0):
                raise ErroNegocio(
                    f"Estoque insuficiente de {peca.codigo} · {peca.descricao}: disponível "
                    f"{(peca.quantidade or 0):g} {peca.unidade or 'UN'}, pedido {quantidade:g}.")
            custo = float(peca.custo_unitario or 0)
            if not math.isfinite(custo) or custo < 0:
                raise ErroNegocio(f"O custo cadastrado de {peca.codigo} é inválido.")

            observacao = f"Ferramenta usada no veículo {veiculo.rotulo}"
            if extra:
                observacao = f"{observacao}. {extra}"
            # A baixa usa o mesmo caminho de toda saída do estoque: o UPDATE é
            # condicional, então duas pessoas baixando ao mesmo tempo não
            # deixam o saldo negativo. O documento definitivo só é conhecido
            # depois do INSERT, por isso começa provisório.
            documento_provisorio = f"FERR-PEND-{uuid4().hex[:24]}"
            movimentar_estoque(peca.id, "saida", quantidade, custo,
                               documento=documento_provisorio,
                               observacao=observacao[:200])
            db.session.flush()
            movimento = MovimentoEstoque.query.filter_by(documento=documento_provisorio).first()
            if not movimento:
                raise ErroNegocio("Não foi possível registrar o histórico da baixa no estoque.")
            movimento.data = data_lancamento

            uso = UsoFerramentaVeiculo(
                data=data_lancamento, veiculo_id=veiculo.id, peca_id=peca.id,
                movimento_estoque_id=movimento.id, quantidade=quantidade,
                custo_unitario=custo, responsavel=responsavel,
                observacao=extra or None, usuario_nome=usuario)
            db.session.add(uso)
            db.session.flush()
            movimento.documento = f"FERR-VEIC-{uso.id}"
            registrar_log("criar", "uso_ferramentas_veiculo", uso.id,
                          f"{peca.codigo} x{quantidade:g} no veículo {veiculo.rotulo}")
            criados.append(uso)

        db.session.commit()
    except (ErroNegocio, ValueError, TypeError, OverflowError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True, "lancamentos": [u.to_dict() for u in criados]}), 201


@bp_ferramentas_caminhoes.delete("/<int:uso_id>")
@editar_tela(TELA)
def cancelar_lancamento(uso_id):
    """Cancela o lançamento e devolve a quantidade ao estoque de peças.

    Exclusão lógica: o registro continua no histórico (aparece como
    Cancelado). Protegida pela senha de administrador (app.py).
    """
    uso = db.get_or_404(UsoFerramentaVeiculo, uso_id)
    try:
        # UPDATE condicional impede devolver duas vezes em cliques simultâneos.
        atualizado = db.session.execute(text("""
            UPDATE uso_ferramentas_veiculo
               SET data_cancelamento = :data, cancelado_por = :usuario,
                   motivo_cancelamento = :motivo
             WHERE id = :id AND data_cancelamento IS NULL"""),
            {"id": uso.id, "data": hoje(),
             "usuario": session.get("usuario_nome") or "Sistema",
             "motivo": "Lançamento cancelado; devolvido ao estoque de peças"})
        if atualizado.rowcount != 1:
            raise ErroNegocio("Este lançamento já foi cancelado.")
        nome_veiculo = uso.veiculo.rotulo if uso.veiculo else f"#{uso.veiculo_id}"
        movimentar_estoque(
            uso.peca_id, "entrada", uso.quantidade, uso.custo_unitario,
            documento=f"Cancelamento FERR-VEIC-{uso.id}",
            observacao=f"Devolução: ferramenta cancelada no veículo {nome_veiculo}"[:200])
        registrar_log("excluir", "uso_ferramentas_veiculo", uso.id,
                      f"Devolvida ao estoque: peça {uso.peca_id}; veículo {nome_veiculo}; "
                      f"quantidade {uso.quantidade:g}; autorizado por "
                      f"{getattr(g, 'admin_autorizador_exclusao', 'administrador')}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True})
