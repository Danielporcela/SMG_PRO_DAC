"""Módulo de Ferramentas dos mecânicos.

Estoque próprio de ferramentas, com o MESMO padrão de lançamento das peças:

1. A nota fiscal nasce "Aberta" e recebe os itens (não mexe no estoque).
2. Ao finalizar a nota, cada item vira uma ENTRADA e o saldo sobe.
3. Quando a ferramenta é colocada em nome de um mecânico (entrega), o sistema
   dá BAIXA no estoque. Cancelar a entrega devolve o saldo.

Toda mudança de saldo passa por `movimentar_ferramenta()` — entrada, saída,
ajuste e estorno usam a mesma função, então a regra vale em qualquer caminho.
"""
import unicodedata

from flask import Blueprint, has_request_context, jsonify, request, session
from sqlalchemy import text

from extensions import db
from models import (EntregaFerramenta, Ferramenta, Fornecedor, Funcionario,
                    ItemNotaFiscalFerramenta, MovimentoFerramenta,
                    NotaFiscalFerramenta, proximo_codigo_ferramenta)
from services.crud import (ErroNegocio, editar_tela, registrar_crud, registrar_log,
                           visualizar_tela)
from services.tempo import hoje, ler_data

bp_ferramentas = Blueprint("ferramentas", __name__, url_prefix="/api")

TELA = "ferramentas"


def _sem_acento(texto):
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def eh_mecanico(funcionario):
    """Mecânico = cargo que contém 'mecânic' (ignora acento e maiúscula),
    então 'Mecânico', 'mecanico' e 'Mecânico de frota' valem."""
    return "mecanic" in _sem_acento(funcionario.cargo)


# ------------------------------------------------------------ saldo (baixa)
def movimentar_ferramenta(ferramenta_id, tipo, quantidade, custo_unitario=0,
                          documento=None, observacao=None, entrega_id=None, data=None):
    """Entrada, saída ou ajuste com registro do movimento e do responsável.

    O saldo é alterado por um UPDATE condicional (não lido-e-regravado em
    Python): se duas pessoas derem baixa da mesma ferramenta ao mesmo tempo, o
    banco resolve a disputa e a segunda recebe "estoque insuficiente".
    """
    ferramenta = db.session.get(Ferramenta, int(ferramenta_id or 0))
    if not ferramenta:
        raise ErroNegocio("Ferramenta não encontrada.")
    quantidade = float(quantidade or 0)
    if quantidade < 0 or (quantidade == 0 and tipo != "ajuste"):
        raise ErroNegocio("Informe uma quantidade maior que zero.")

    if tipo == "entrada":
        preco = float(custo_unitario or ferramenta.custo_unitario or 0)
        # Custo médio ponderado, igual ao estoque de peças.
        db.session.execute(text("""
            UPDATE ferramentas
               SET custo_unitario = CASE
                       WHEN COALESCE(quantidade, 0) + :qtd > 0
                       THEN ROUND(CAST((COALESCE(quantidade, 0) * COALESCE(custo_unitario, 0)
                                   + :qtd * :preco) / (COALESCE(quantidade, 0) + :qtd)
                                  AS numeric), 2)
                       ELSE :preco END,
                   quantidade = COALESCE(quantidade, 0) + :qtd
             WHERE id = :id"""), {"qtd": quantidade, "preco": preco, "id": ferramenta.id})
    elif tipo == "saida":
        resultado = db.session.execute(text("""
            UPDATE ferramentas
               SET quantidade = COALESCE(quantidade, 0) - :qtd
             WHERE id = :id AND COALESCE(quantidade, 0) >= :qtd"""),
            {"qtd": quantidade, "id": ferramenta.id})
        if resultado.rowcount == 0:
            db.session.refresh(ferramenta)
            raise ErroNegocio(f"Estoque insuficiente de {ferramenta.codigo} · "
                              f"{ferramenta.descricao}: disponível "
                              f"{(ferramenta.quantidade or 0):g} {ferramenta.unidade or 'UN'}.")
    elif tipo == "ajuste":  # define o saldo informado
        db.session.execute(text("UPDATE ferramentas SET quantidade = :qtd WHERE id = :id"),
                           {"qtd": quantidade, "id": ferramenta.id})
    else:
        raise ErroNegocio("Tipo de movimento inválido.")

    db.session.refresh(ferramenta)

    usuario_id = usuario_nome = None
    if has_request_context():
        usuario_id = session.get("usuario_id")
        usuario_nome = session.get("usuario_nome")
    db.session.add(MovimentoFerramenta(
        data=data or hoje(), ferramenta_id=ferramenta.id, tipo=tipo, quantidade=quantidade,
        custo_unitario=float(custo_unitario or ferramenta.custo_unitario or 0),
        documento=documento, entrega_id=entrega_id, observacao=observacao,
        usuario_id=usuario_id, usuario_nome=usuario_nome or "Sistema"))
    return ferramenta


# ------------------------------------------------------ cadastro (catálogo)
def _antes_ferramenta(obj, dados, anterior):
    if not (obj.codigo or "").strip():
        # Criação: gera 0001, 0002... Edição: o código nunca fica em branco.
        obj.codigo = (anterior or {}).get("codigo") or proximo_codigo_ferramenta()
    obj.codigo = obj.codigo.strip()
    obj.unidade = (obj.unidade or "UN").strip().upper()[:10] or "UN"
    # O saldo só muda por movimento — nunca pelo cadastro.
    if anterior is None:
        obj.quantidade = 0


def _depois_ferramenta(obj, dados, anterior):
    """Saldo inicial entra como movimento, para nunca existir saldo sem histórico."""
    if anterior is not None:
        return
    try:
        inicial = float(dados.get("quantidade_inicial") or 0)
    except (TypeError, ValueError):
        raise ErroNegocio("Saldo inicial inválido.")
    if inicial < 0:
        raise ErroNegocio("O saldo inicial não pode ser negativo.")
    if inicial > 0:
        movimentar_ferramenta(obj.id, "entrada", inicial, obj.custo_unitario,
                              documento="Saldo inicial", observacao="Cadastro da ferramenta")


def _antes_excluir_ferramenta(obj):
    em_uso = (MovimentoFerramenta.query.filter_by(ferramenta_id=obj.id).first()
              or EntregaFerramenta.query.filter_by(ferramenta_id=obj.id).first()
              or ItemNotaFiscalFerramenta.query.filter_by(ferramenta_id=obj.id).first())
    if em_uso:
        raise ErroNegocio("Esta ferramenta já tem movimentação. Em vez de excluir, "
                          "desmarque \"ativa\" para tirá-la das listas.")


registrar_crud(
    bp_ferramentas, "ferramentas", Ferramenta,
    campos={"codigo": "str", "descricao": "str", "marca": "str", "unidade": "str",
            "estoque_minimo": "float", "custo_unitario": "float",
            "localizacao": "str", "ativo": "bool"},
    ordem=Ferramenta.descricao, obrigatorios=("descricao",), tela=TELA,
    antes_salvar=_antes_ferramenta, depois_salvar=_depois_ferramenta,
    antes_excluir=_antes_excluir_ferramenta)


@bp_ferramentas.get("/ferramentas/mecanicos")
@visualizar_tela(TELA)
def listar_mecanicos():
    """Funcionários ativos com cargo de mecânico — quem pode receber ferramenta."""
    funcionarios = (Funcionario.query.filter(Funcionario.ativo.is_(True))
                    .order_by(Funcionario.nome).all())
    return jsonify([f.to_dict() for f in funcionarios if eh_mecanico(f)])


@bp_ferramentas.post("/ferramentas/mecanicos")
@editar_tela(TELA)
def cadastrar_mecanico():
    """Cadastra um mecânico sem sair da tela de Ferramentas.

    Quem tem 'editar' em Ferramentas não precisa de acesso à tela de
    Funcionários: o registro criado é um Funcionário comum (aparece lá também),
    mas o cargo é sempre "Mecânico" — assim ele já entra na lista de quem pode
    receber ferramenta.
    """
    dados = request.get_json(silent=True) or {}
    try:
        nome = " ".join((dados.get("nome") or "").split())
        if not nome:
            raise ErroNegocio("Informe o nome do mecânico.")
        if len(nome) > 120:
            raise ErroNegocio("O nome pode ter no máximo 120 caracteres.")
        matricula = (dados.get("matricula") or "").strip() or None
        telefone = (dados.get("telefone") or "").strip() or None
        if matricula and len(matricula) > 30:
            raise ErroNegocio("A matrícula pode ter no máximo 30 caracteres.")
        if telefone and len(telefone) > 20:
            raise ErroNegocio("O telefone pode ter no máximo 20 caracteres.")

        # Evita duplicar a pessoa (ignora acento, maiúscula e espaço extra).
        chave = _sem_acento(nome)
        for existente in Funcionario.query.all():
            if _sem_acento(" ".join((existente.nome or "").split())) != chave:
                continue
            if existente.ativo and eh_mecanico(existente):
                raise ErroNegocio(f"{existente.nome} já está cadastrado como mecânico.")
            raise ErroNegocio(
                f"Já existe um funcionário chamado {existente.nome} "
                f"({existente.cargo or 'sem cargo'}"
                f"{'' if existente.ativo else ', inativo'}). Ajuste o cargo ou reative "
                "o cadastro em Cadastros > Funcionários.")

        mecanico = Funcionario(nome=nome, matricula=matricula, telefone=telefone,
                               setor=(dados.get("setor") or "").strip()[:60] or "Oficina",
                               cargo="Mecânico", ativo=True)
        db.session.add(mecanico)
        db.session.flush()
        registrar_log("criar", "funcionarios", mecanico.id,
                      f"Mecânico cadastrado pela tela de Ferramentas: {mecanico.nome}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(mecanico.to_dict()), 201


# --------------------------------------------------------------- movimentos
@bp_ferramentas.get("/ferramentas/movimentos")
@visualizar_tela(TELA)
def listar_movimentos_ferramenta():
    q = MovimentoFerramenta.query
    if request.args.get("ferramenta_id"):
        q = q.filter(MovimentoFerramenta.ferramenta_id == int(request.args["ferramenta_id"]))
    inicio = ler_data(request.args.get("inicio"), "início do período")
    fim = ler_data(request.args.get("fim"), "fim do período")
    if inicio:
        q = q.filter(MovimentoFerramenta.data >= inicio)
    if fim:
        q = q.filter(MovimentoFerramenta.data <= fim)
    return jsonify([m.to_dict() for m in
                    q.order_by(MovimentoFerramenta.id.desc()).limit(300)])


@bp_ferramentas.post("/ferramentas/ajuste")
@editar_tela(TELA)
def ajustar_saldo_ferramenta():
    """Correção de inventário: define o saldo contado. Exige o motivo."""
    dados = request.get_json(silent=True) or {}
    try:
        motivo = (dados.get("observacao") or "").strip()
        if not motivo:
            raise ErroNegocio("Informe o motivo do ajuste de saldo.")
        if dados.get("quantidade") in (None, ""):
            raise ErroNegocio("Informe o saldo contado.")
        ferramenta = movimentar_ferramenta(
            dados.get("ferramenta_id"), "ajuste", dados.get("quantidade"),
            documento="Ajuste de inventário", observacao=motivo)
        registrar_log("editar", "ferramentas", ferramenta.id,
                      f"Ajuste de saldo: {ferramenta.codigo} = {ferramenta.quantidade:g}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(ferramenta.to_dict())


# ------------------------------------------------------------ notas fiscais
def _nota_aberta(nota):
    if nota.status != "Aberta":
        raise ErroNegocio("Esta nota já foi finalizada e não pode mais ser alterada.")


def _verificar_nota_duplicada(fornecedor_id, nota_id=None):
    """Mesma regra da NF de peças: uma nota aberta por fornecedor por vez."""
    if not fornecedor_id:
        return
    q = NotaFiscalFerramenta.query.filter(
        NotaFiscalFerramenta.fornecedor_id == fornecedor_id,
        NotaFiscalFerramenta.status.notin_(("Finalizada", "Cancelada")))
    if nota_id is not None:
        q = q.filter(NotaFiscalFerramenta.id != nota_id)
    conflito = q.first()
    if conflito:
        fornecedor = db.session.get(Fornecedor, fornecedor_id)
        nome = fornecedor.nome if fornecedor else "este fornecedor"
        raise ErroNegocio(
            f"Já existe a nota fiscal {conflito.numero} de {nome} aberta "
            f"(status: {conflito.status}). Finalize-a antes de lançar uma nova nota "
            f"para o mesmo fornecedor.")


@bp_ferramentas.get("/notas_fiscais_ferramenta")
@visualizar_tela(TELA)
def listar_notas_ferramenta():
    q = NotaFiscalFerramenta.query
    inicio = ler_data(request.args.get("inicio"), "início do período")
    fim = ler_data(request.args.get("fim"), "fim do período")
    if inicio:
        q = q.filter(NotaFiscalFerramenta.data_emissao >= inicio)
    if fim:
        q = q.filter(NotaFiscalFerramenta.data_emissao <= fim)
    q = q.order_by(NotaFiscalFerramenta.data_emissao.desc(), NotaFiscalFerramenta.id.desc())
    return jsonify([n.to_dict() for n in q.all()])


@bp_ferramentas.get("/notas_fiscais_ferramenta/<int:nota_id>")
@visualizar_tela(TELA)
def obter_nota_ferramenta(nota_id):
    return jsonify(db.get_or_404(NotaFiscalFerramenta, nota_id).to_dict(com_itens=True))


@bp_ferramentas.post("/notas_fiscais_ferramenta")
@editar_tela(TELA)
def criar_nota_ferramenta():
    dados = request.get_json(silent=True) or {}
    if not dados.get("numero") or not dados.get("fornecedor_id"):
        return jsonify({"erro": "Preencha: Número, Fornecedor"}), 400
    try:
        fornecedor_id = int(dados["fornecedor_id"])
        if not db.session.get(Fornecedor, fornecedor_id):
            raise ErroNegocio("Fornecedor não encontrado.")
        _verificar_nota_duplicada(fornecedor_id)
        nota = NotaFiscalFerramenta(
            numero=str(dados["numero"]).strip(),
            serie=(dados.get("serie") or "").strip() or None,
            data_emissao=ler_data(dados.get("data_emissao"), "data de emissão") or hoje(),
            fornecedor_id=fornecedor_id,
            observacao=(dados.get("observacao") or "").strip() or None)
        db.session.add(nota)
        db.session.flush()
        registrar_log("criar", "notas_fiscais_ferramenta", nota.id, f"NF {nota.numero}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict()), 201


@bp_ferramentas.delete("/notas_fiscais_ferramenta/<int:nota_id>")
@editar_tela(TELA)
def excluir_nota_ferramenta(nota_id):
    nota = db.get_or_404(NotaFiscalFerramenta, nota_id)
    try:
        _nota_aberta(nota)
        registrar_log("excluir", "notas_fiscais_ferramenta", nota_id, f"NF {nota.numero}")
        db.session.delete(nota)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True})


@bp_ferramentas.post("/notas_fiscais_ferramenta/<int:nota_id>/itens")
@editar_tela(TELA)
def adicionar_item_nota_ferramenta(nota_id):
    nota = db.get_or_404(NotaFiscalFerramenta, nota_id)
    dados = request.get_json(silent=True) or {}
    try:
        _nota_aberta(nota)
        if not dados.get("ferramenta_id"):
            raise ErroNegocio("Selecione a ferramenta.")
        ferramenta = db.session.get(Ferramenta, int(dados["ferramenta_id"]))
        if not ferramenta:
            raise ErroNegocio("Ferramenta não encontrada.")
        quantidade = float(dados.get("quantidade") or 0)
        if quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")
        valor = float(dados.get("valor_unitario") or ferramenta.custo_unitario or 0)
        if valor < 0:
            raise ErroNegocio("O valor unitário não pode ser negativo.")
        db.session.add(ItemNotaFiscalFerramenta(
            nota_fiscal_id=nota.id, ferramenta_id=ferramenta.id,
            descricao=(dados.get("descricao") or ferramenta.descricao),
            quantidade=quantidade, valor_unitario=valor))
        registrar_log("criar", "itens_nota_fiscal_ferramenta", nota.id,
                      f"NF {nota.numero}: {ferramenta.codigo}")
        db.session.commit()
        db.session.refresh(nota)
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True)), 201


@bp_ferramentas.delete("/notas_fiscais_ferramenta/<int:nota_id>/itens/<int:item_id>")
@editar_tela(TELA)
def remover_item_nota_ferramenta(nota_id, item_id):
    nota = db.get_or_404(NotaFiscalFerramenta, nota_id)
    item = db.get_or_404(ItemNotaFiscalFerramenta, item_id)
    try:
        _nota_aberta(nota)
        if item.nota_fiscal_id != nota.id:
            raise ErroNegocio("Este item não pertence a esta nota.")
        db.session.delete(item)
        db.session.commit()
        db.session.refresh(nota)
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(nota.to_dict(com_itens=True))


@bp_ferramentas.post("/notas_fiscais_ferramenta/<int:nota_id>/finalizar")
@editar_tela(TELA)
def finalizar_nota_ferramenta(nota_id):
    """Dá entrada no estoque de cada item e trava a nota — ação irreversível."""
    nota = db.get_or_404(NotaFiscalFerramenta, nota_id)
    try:
        _nota_aberta(nota)
        if not nota.itens:
            raise ErroNegocio("Lance ao menos um item antes de finalizar a nota.")
        documento = f"NF {nota.numero}" + (f"/{nota.serie}" if nota.serie else "")
        for item in nota.itens:
            if item.baixado_estoque:
                continue
            movimentar_ferramenta(item.ferramenta_id, "entrada", item.quantidade,
                                  item.valor_unitario, documento=documento,
                                  observacao=f"Entrada pela nota fiscal de ferramentas #{nota.id}")
            item.baixado_estoque = True
        nota.status = "Finalizada"
        nota.data_entrada = hoje()
        registrar_log("finalizar", "notas_fiscais_ferramenta", nota.id, f"NF {nota.numero}")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"erro": f"Não foi possível finalizar: {e.__class__.__name__}."}), 400
    return jsonify(nota.to_dict(com_itens=True))


# ------------------------------------------- ferramenta em nome do mecânico
@bp_ferramentas.get("/entregas_ferramenta")
@visualizar_tela(TELA)
def listar_entregas_ferramenta():
    q = EntregaFerramenta.query
    if request.args.get("funcionario_id"):
        q = q.filter(EntregaFerramenta.funcionario_id == int(request.args["funcionario_id"]))
    if request.args.get("ferramenta_id"):
        q = q.filter(EntregaFerramenta.ferramenta_id == int(request.args["ferramenta_id"]))
    inicio = ler_data(request.args.get("inicio"), "início do período")
    fim = ler_data(request.args.get("fim"), "fim do período")
    if inicio:
        q = q.filter(EntregaFerramenta.data >= inicio)
    if fim:
        q = q.filter(EntregaFerramenta.data <= fim)
    q = q.order_by(EntregaFerramenta.data.desc(), EntregaFerramenta.id.desc())
    return jsonify([e.to_dict() for e in q.limit(500).all()])


@bp_ferramentas.post("/entregas_ferramenta")
@editar_tela(TELA)
def criar_entrega_ferramenta():
    """Coloca a ferramenta em nome do mecânico e DÁ BAIXA no estoque."""
    dados = request.get_json(silent=True) or {}
    try:
        if not dados.get("funcionario_id") or not dados.get("ferramenta_id"):
            raise ErroNegocio("Selecione o mecânico e a ferramenta.")
        mecanico = db.session.get(Funcionario, int(dados["funcionario_id"]))
        if not mecanico:
            raise ErroNegocio("Mecânico não encontrado.")
        if not mecanico.ativo:
            raise ErroNegocio(f"{mecanico.nome} está inativo.")
        if not eh_mecanico(mecanico):
            raise ErroNegocio(f"{mecanico.nome} não está cadastrado com o cargo de mecânico. "
                              "Ajuste o cargo em Cadastros > Funcionários.")
        ferramenta = db.session.get(Ferramenta, int(dados["ferramenta_id"]))
        if not ferramenta:
            raise ErroNegocio("Ferramenta não encontrada.")
        if not ferramenta.ativo:
            raise ErroNegocio(f"A ferramenta {ferramenta.codigo} está inativa.")
        # Só assume 1 quando nada foi informado — um 0 digitado deve ser recusado.
        bruto = dados.get("quantidade")
        quantidade = 1.0 if bruto in (None, "") else float(bruto)
        if quantidade <= 0:
            raise ErroNegocio("Informe uma quantidade maior que zero.")

        data_entrega = ler_data(dados.get("data"), "data da entrega") or hoje()
        entrega = EntregaFerramenta(
            data=data_entrega, funcionario_id=mecanico.id, ferramenta_id=ferramenta.id,
            quantidade=quantidade, custo_unitario=ferramenta.custo_unitario or 0,
            observacao=(dados.get("observacao") or "").strip() or None,
            usuario_nome=session.get("usuario_nome"))
        db.session.add(entrega)
        db.session.flush()

        movimentar_ferramenta(
            ferramenta.id, "saida", quantidade, ferramenta.custo_unitario,
            documento=f"Entrega #{entrega.id} — {mecanico.nome}",
            observacao=f"Ferramenta em nome do mecânico {mecanico.nome}",
            entrega_id=entrega.id, data=data_entrega)

        registrar_log("criar", "entregas_ferramenta", entrega.id,
                      f"{ferramenta.codigo} x{quantidade:g} para {mecanico.nome}")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify(entrega.to_dict()), 201


@bp_ferramentas.delete("/entregas_ferramenta/<int:entrega_id>")
@editar_tela(TELA)
def cancelar_entrega_ferramenta(entrega_id):
    """Cancela a entrega (lançamento errado ou devolução) e devolve ao estoque."""
    entrega = db.get_or_404(EntregaFerramenta, entrega_id)
    try:
        nome = entrega.funcionario.nome if entrega.funcionario else ""
        movimentar_ferramenta(
            entrega.ferramenta_id, "entrada", entrega.quantidade, entrega.custo_unitario,
            documento=f"Estorno da entrega #{entrega.id}",
            observacao=f"Cancelamento — ferramenta devolvida por {nome}".strip(" —"),
            entrega_id=entrega.id)
        registrar_log("excluir", "entregas_ferramenta", entrega.id,
                      f"Estornada: {entrega.ferramenta_id} de {nome}")
        db.session.delete(entrega)
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True})
