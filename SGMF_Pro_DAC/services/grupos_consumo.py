"""Regras dos grupos de consumo interno e compatibilidade com cadastros antigos."""
from datetime import date
import unicodedata

from extensions import db
from models import GrupoConsumo, MovimentoEstoque, Orcamento, OrdemServico, Veiculo


GRUPOS_CONSUMO_PADRAO = (
    "Limpeza",
    "Escritório",
    "CCO",
    "Capatazia Centro",
    "Capatazia Sul",
    "Solda",
    "Borracheiro",
    "Oficina",
)


def _normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.upper().strip().split())


def eh_grupo_padrao(nome):
    alvo = _normalizar(nome)
    return alvo in {_normalizar(item) for item in GRUPOS_CONSUMO_PADRAO}


def nome_grupo_consumo_legado(veiculo):
    """Reconhece os setores que no sistema antigo foram cadastrados como veículos."""
    if not veiculo:
        return None
    prefixo = _normalizar(veiculo.prefixo)
    placa = _normalizar(veiculo.placa)
    marca = _normalizar(veiculo.marca)
    modelo = _normalizar(veiculo.modelo)
    conjunto = " ".join((prefixo, placa, marca, modelo))

    if prefixo == "LIMPEZA" or placa == "LIMPEZA":
        return "Limpeza"
    if prefixo in {"ESCRITORIO", "ESCRITÓRIO"}:
        return "Escritório"
    if prefixo == "CCO" or placa == "CCO":
        return "CCO"
    if prefixo.startswith("CAPATAZIA") or prefixo.startswith("CAPATZIA"):
        if "SUL" in conjunto:
            return "Capatazia Sul"
        if "CENTRO" in conjunto:
            return "Capatazia Centro"
    if prefixo in {"BORRACHARIA", "BORRACHEIRO"} or placa in {"BORRACHARIA", "BORRACHEIRO"}:
        return "Borracheiro"
    if prefixo == "SOLDA" or marca == "SOLDA" or modelo == "SOLDA":
        return "Solda"
    if prefixo == "OFICINA" or (placa in {"MECANICA", "MECÂNICA"} and "OFICINA" in conjunto):
        return "Oficina"
    return None


def garantir_grupos_padrao():
    existentes = {_normalizar(g.nome): g for g in GrupoConsumo.query.all()}
    criados = []
    for nome in GRUPOS_CONSUMO_PADRAO:
        chave = _normalizar(nome)
        if chave in existentes:
            continue
        grupo = GrupoConsumo(nome=nome, ativo=True)
        db.session.add(grupo)
        existentes[chave] = grupo
        criados.append(grupo)
    if criados:
        db.session.flush()
    return criados


def marcar_veiculos_grupo_consumo_legado():
    """Oculta da frota os setores antigos sem apagar veículos, OS ou históricos."""
    alterados = []
    for veiculo in Veiculo.query.all():
        nome = nome_grupo_consumo_legado(veiculo)
        if nome and not veiculo.grupo_consumo_legado:
            veiculo.grupo_consumo_legado = True
            alterados.append((veiculo.id, nome))
    if alterados:
        db.session.flush()
    return alterados


def grupo_por_nome(nome):
    alvo = _normalizar(nome)
    for grupo in GrupoConsumo.query.all():
        if _normalizar(grupo.nome) == alvo:
            return grupo
    return None


def grupo_para_veiculo_legado(veiculo):
    nome = nome_grupo_consumo_legado(veiculo)
    return grupo_por_nome(nome) if nome else None


def grupo_para_ordem(ordem_id):
    if not ordem_id:
        return None
    ordem = db.session.get(OrdemServico, ordem_id)
    if not ordem or not ordem.veiculo or not ordem.veiculo.grupo_consumo_legado:
        return None
    return grupo_para_veiculo_legado(ordem.veiculo)


def _meses_no_periodo(inicio, fim):
    atual = date(inicio.year, inicio.month, 1)
    limite = date(fim.year, fim.month, 1)
    meses = set()
    while atual <= limite:
        meses.add((atual.year, atual.month))
        if atual.month == 12:
            atual = date(atual.year + 1, 1, 1)
        else:
            atual = date(atual.year, atual.month + 1, 1)
    return meses


def custos_por_grupo(inicio, fim):
    """Consolida retiradas novas e consumos antigos feitos por veículos setor."""
    grupos = GrupoConsumo.query.order_by(GrupoConsumo.nome).all()
    por_id = {
        g.id: {
            "id": g.id,
            "nome": g.nome,
            "ativo": bool(g.ativo),
            "movimentos": 0,
            "quantidade": 0.0,
            "realizado": 0.0,
            "meta": 0.0,
        }
        for g in grupos
    }

    diretos = (MovimentoEstoque.query
               .filter(MovimentoEstoque.tipo == "saida",
                       MovimentoEstoque.grupo_consumo_id.isnot(None),
                       MovimentoEstoque.data.between(inicio, fim)).all())
    for mov in diretos:
        registro = por_id.get(mov.grupo_consumo_id)
        if not registro:
            continue
        registro["movimentos"] += 1
        registro["quantidade"] += mov.quantidade or 0
        registro["realizado"] += (mov.quantidade or 0) * (mov.custo_unitario or 0)

    legados = (db.session.query(MovimentoEstoque, Veiculo)
               .join(OrdemServico, MovimentoEstoque.ordem_servico_id == OrdemServico.id)
               .join(Veiculo, OrdemServico.veiculo_id == Veiculo.id)
               .filter(MovimentoEstoque.tipo == "saida",
                       MovimentoEstoque.grupo_consumo_id.is_(None),
                       MovimentoEstoque.data.between(inicio, fim),
                       Veiculo.grupo_consumo_legado.is_(True)).all())
    for mov, veiculo in legados:
        grupo = grupo_para_veiculo_legado(veiculo)
        if not grupo or grupo.id not in por_id:
            continue
        registro = por_id[grupo.id]
        registro["movimentos"] += 1
        registro["quantidade"] += mov.quantidade or 0
        registro["realizado"] += (mov.quantidade or 0) * (mov.custo_unitario or 0)

    meses = _meses_no_periodo(inicio, fim)
    for meta in Orcamento.query.filter(Orcamento.grupo_consumo_id.isnot(None)).all():
        if (meta.ano, meta.mes) not in meses:
            continue
        registro = por_id.get(meta.grupo_consumo_id)
        if registro:
            registro["meta"] += meta.meta_valor or 0

    metas_legadas = (db.session.query(Orcamento, Veiculo)
                     .join(Veiculo, Orcamento.veiculo_id == Veiculo.id)
                     .filter(Orcamento.grupo_consumo_id.is_(None),
                             Veiculo.grupo_consumo_legado.is_(True)).all())
    for meta, veiculo in metas_legadas:
        if (meta.ano, meta.mes) not in meses:
            continue
        grupo = grupo_para_veiculo_legado(veiculo)
        registro = por_id.get(grupo.id) if grupo else None
        if registro:
            registro["meta"] += meta.meta_valor or 0

    saida = []
    for registro in por_id.values():
        registro["quantidade"] = round(registro["quantidade"], 2)
        registro["realizado"] = round(registro["realizado"], 2)
        registro["meta"] = round(registro["meta"], 2)
        registro["saldo_meta"] = round(registro["meta"] - registro["realizado"], 2)
        registro["percentual_meta"] = (
            round(registro["realizado"] / registro["meta"] * 100, 1)
            if registro["meta"] else None
        )
        registro["situacao"] = (
            "Acima da meta" if registro["meta"] and registro["realizado"] > registro["meta"]
            else "Dentro da meta" if registro["meta"] else "Sem meta"
        )
        saida.append(registro)
    return saida


def movimentos_por_grupo(inicio, fim, grupo_id=None, limite=250):
    itens = []
    diretos = (MovimentoEstoque.query
               .filter(MovimentoEstoque.tipo == "saida",
                       MovimentoEstoque.grupo_consumo_id.isnot(None),
                       MovimentoEstoque.data.between(inicio, fim)).all())
    for mov in diretos:
        if grupo_id and mov.grupo_consumo_id != grupo_id:
            continue
        dado = mov.to_dict()
        dado["origem"] = "Grupo de consumo"
        itens.append(dado)

    legados = (db.session.query(MovimentoEstoque, Veiculo)
               .join(OrdemServico, MovimentoEstoque.ordem_servico_id == OrdemServico.id)
               .join(Veiculo, OrdemServico.veiculo_id == Veiculo.id)
               .filter(MovimentoEstoque.tipo == "saida",
                       MovimentoEstoque.grupo_consumo_id.is_(None),
                       MovimentoEstoque.data.between(inicio, fim),
                       Veiculo.grupo_consumo_legado.is_(True)).all())
    for mov, veiculo in legados:
        grupo = grupo_para_veiculo_legado(veiculo)
        if not grupo or (grupo_id and grupo.id != grupo_id):
            continue
        dado = mov.to_dict()
        dado["grupo_consumo_id"] = grupo.id
        dado["grupo_consumo_nome"] = grupo.nome
        dado["origem"] = "Histórico anterior"
        itens.append(dado)

    itens.sort(key=lambda d: (d.get("data") or "", d.get("id") or 0), reverse=True)
    return itens[:limite]
