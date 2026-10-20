"""Relatório consolidado do "Gasto total" do painel.

Os valores do resumo vêm de `indicadores.resumo` — a MESMA função que alimenta
o card "Gasto total" do painel —, então o relatório sempre fecha com o que a
tela mostra. O detalhamento lista os lançamentos que compõem cada categoria.
"""
from services import indicadores
from services.grupos_consumo import custos_por_grupo
from services.tempo import hoje


def _data(d):
    return d.strftime("%d/%m/%Y") if d else "—"


def _veiculo(v):
    return f"{v.prefixo}/{v.placa}" if v else "—"


def _nf(nota):
    return f"NF {nota.numero}" + (f"/{nota.serie}" if nota.serie else "")


def _r(valor):
    return round(float(valor or 0), 2)


def montar(inicio, fim):
    """Retorna um dicionário com resumo, detalhamento por categoria e meta."""
    r = indicadores.resumo(inicio.isoformat(), fim.isoformat())

    # ---- resumo por categoria (ordem igual à nota do card) ------------------
    categorias = [
        ("Manutenção (OS)", r["gasto_manutencao_os"],
         r["os_finalizadas"] + r["os_abertas"], "OS no período"),
        ("Serviços de terceiros", r["gasto_servicos_terceiros"],
         r["servicos_terceiros_qtd"], "lançamento(s)"),
        ("Lavagem", r["gasto_lavagem"], r["lavagens_qtd"], "lançamento(s)"),
        ("Uniformes (NF)", r["gasto_uniformes"], r["notas_uniformes_qtd"], "nota(s) finalizada(s)"),
        ("Grupos de consumo", r["gasto_grupos_consumo"], None, "retirada(s)"),
        ("Ferramentas dos mecânicos", r["gasto_ferramentas_mecanicos"],
         r["transferencias_ferramentas_qtd"], "transferência(s)"),
    ]
    grupos = custos_por_grupo(inicio, fim)
    qtd_grupos = sum(g["movimentos"] for g in grupos)
    total = r["gasto_total"]
    resumo = []
    for nome, valor, qtd, unidade in categorias:
        if nome == "Grupos de consumo":
            qtd = qtd_grupos
        resumo.append({
            "categoria": nome, "valor": _r(valor), "qtd": qtd or 0, "unidade": unidade,
            "percentual": round(valor / total * 100, 1) if total else 0.0,
        })

    meta = r["orcamento_mes"]
    # O card compara com a meta só manutenção + lavagem + uniformes (regra do painel).
    base_meta = _r(r["gasto_manutencao"] + r["gasto_lavagem"] + r["gasto_uniformes"])

    dados = {
        "inicio": inicio, "fim": fim, "emitido_em": hoje(),
        "resumo": resumo,
        "gasto_manutencao": _r(r["gasto_manutencao"]),   # OS + terceiros
        "gasto_total": _r(total),
        "gasto_total_geral": _r(r["gasto_total_geral"]),
        "meta": _r(meta),
        "base_meta": base_meta,
        "aderencia": r["aderencia_orcamento"] if meta else None,
        "saldo_meta": _r(meta - base_meta) if meta else None,
        "combustivel": _r(r["gasto_combustivel"]),
        "compras_nf": _r(r["gasto_compras"]),
    }

    # ---- detalhamento -------------------------------------------------------
    from models import Lavagem, NotaFiscalUniforme, ServicoTerceiro, TransferenciaFerramenta

    dados["det_os"] = [
        [o.numero, _data(o.data_abertura), _veiculo(o.veiculo), o.tipo or "—", o.status or "—",
         o.fornecedor.nome if o.fornecedor else "—",
         _r(o.custo_pecas), _r(o.custo_mao_obra), _r(o.custo_servicos_total), _r(o.custo_total)]
        for o in sorted(indicadores._custo_os(inicio, fim),
                        key=lambda o: (o.data_abertura or inicio, o.id))
    ]
    dados["det_terceiros"] = [
        [_data(s.data), s.ordem.numero if s.ordem else "—", _veiculo(s.veiculo),
         s.prestador or "—", s.categoria or "—", s.nota_fiscal or s.documento or "—",
         s.descricao or "—", _r(s.valor)]
        for s in sorted(indicadores._servicos_terceiros(inicio, fim),
                        key=lambda s: (s.data, s.id))
    ]
    dados["det_lavagem"] = [
        [_data(l.data), _veiculo(l.veiculo), l.observacao or "—", _r(l.valor)]
        for l in sorted(indicadores._lavagens(inicio, fim), key=lambda l: (l.data, l.id))
    ]
    dados["det_uniformes"] = []
    for n in sorted(indicadores._notas_uniformes_finalizadas(inicio, fim),
                    key=lambda n: (n.data_entrada, n.id)):
        for it in n.itens:
            dados["det_uniformes"].append([
                _nf(n), _data(n.data_entrada),
                n.fornecedor.nome if n.fornecedor else "—",
                it.item_uniforme.descricao if it.item_uniforme else "—", it.tamanho,
                round(it.quantidade or 0, 2), _r(it.valor_unitario), _r(it.subtotal)])
    dados["det_grupos"] = [
        [g["nome"], g["movimentos"], g["quantidade"], g["realizado"], g["meta"],
         g["saldo_meta"], g["situacao"]]
        for g in grupos if g["movimentos"] or g["realizado"] or g["meta"]
    ]
    dados["det_ferramentas"] = [
        [_data(t.data), f"{t.peca.codigo} - {t.peca.descricao}" if t.peca else "—",
         f"{t.ferramenta.codigo} - {t.ferramenta.descricao}" if t.ferramenta else "—",
         round(t.quantidade or 0, 2), _r(t.custo_unitario), _r(t.valor_total),
         t.usuario_nome or "—"]
        for t in TransferenciaFerramenta.query
        .filter(TransferenciaFerramenta.data.between(inicio, fim))
        .order_by(TransferenciaFerramenta.data, TransferenciaFerramenta.id).all()
    ]
    return dados


# Definição de cada seção de detalhe: (chave, título, cabeçalhos, índices de colunas monetárias)
SECOES = [
    ("det_os", "Manutenção — Ordens de serviço",
     ["OS", "Abertura", "Veículo", "Tipo", "Status", "Oficina",
      "Peças R$", "Mão de obra R$", "Serviços R$", "Total R$"], [6, 7, 8, 9]),
    ("det_terceiros", "Serviços de terceiros",
     ["Data", "OS", "Veículo", "Prestador", "Categoria", "NF / Doc.", "Descrição", "Valor R$"], [7]),
    ("det_lavagem", "Lavagem", ["Data", "Veículo", "Observação", "Valor R$"], [3]),
    ("det_uniformes", "Uniformes (NF finalizadas)",
     ["NF", "Entrada", "Fornecedor", "Uniforme", "Tamanho", "Qtd", "Valor unit. R$", "Subtotal R$"], [6, 7]),
    ("det_grupos", "Grupos de consumo",
     ["Grupo", "Retiradas", "Quantidade", "Realizado R$", "Meta R$", "Saldo da meta R$", "Situação"], [3]),
    ("det_ferramentas", "Ferramentas dos mecânicos (transferências do estoque)",
     ["Data", "Peça", "Ferramenta", "Qtd", "Custo unit. R$", "Total R$", "Usuário"], [4, 5]),
]
