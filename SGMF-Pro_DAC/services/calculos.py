"""Cálculos automáticos disparados quando um registro é salvo."""
from datetime import date

from sqlalchemy import text

from services.tempo import hoje

from extensions import db
from models import (Abastecimento, ItemNotaFiscal, ItemOS, MovimentoEstoque, NotaFiscal,
                    OrdemServico, Peca, Pneu, Veiculo)
from services.crud import ErroNegocio


# ------------------------------------------------------------ combustível
def recalcular_abastecimento(abast):
    """Km percorridos, km/L e custo por km a partir do abastecimento anterior."""
    if abast.litros and abast.valor_litro and not abast.valor_total:
        abast.valor_total = round(abast.litros * abast.valor_litro, 2)
    if abast.litros and abast.valor_total and not abast.valor_litro:
        abast.valor_litro = round(abast.valor_total / abast.litros, 3)

    anterior = (Abastecimento.query
                .filter(Abastecimento.veiculo_id == abast.veiculo_id,
                        Abastecimento.id != abast.id,
                        Abastecimento.km_atual < (abast.km_atual or 0))
                .order_by(Abastecimento.km_atual.desc())
                .first())

    if anterior and abast.km_atual:
        abast.km_percorridos = round(abast.km_atual - anterior.km_atual, 1)
    else:
        abast.km_percorridos = 0

    if abast.km_percorridos and abast.litros:
        abast.km_por_litro = round(abast.km_percorridos / abast.litros, 2)
        abast.custo_por_km = round((abast.valor_total or 0) / abast.km_percorridos, 3)
    else:
        abast.km_por_litro = 0
        abast.custo_por_km = 0

    # o hodômetro do veículo acompanha o maior km lançado
    veiculo = db.session.get(Veiculo, abast.veiculo_id)
    if veiculo and (abast.km_atual or 0) > (veiculo.hodometro or 0):
        veiculo.hodometro = abast.km_atual
    return abast


def validar_km(abast):
    veiculo = db.session.get(Veiculo, abast.veiculo_id)
    if not veiculo:
        raise ErroNegocio("Selecione um veículo válido.")
    ultimo = (Abastecimento.query
              .filter(Abastecimento.veiculo_id == abast.veiculo_id,
                      Abastecimento.id != abast.id)
              .order_by(Abastecimento.km_atual.desc()).first())
    if ultimo and (abast.km_atual or 0) < ultimo.km_atual:
        raise ErroNegocio(f"O km informado ({abast.km_atual:.0f}) é menor que o último "
                          f"registrado para este veículo ({ultimo.km_atual:.0f}).")


# ---------------------------------------------------------------- estoque
def movimentar_estoque(peca_id, tipo, quantidade, custo_unitario=0, os_id=None,
                       documento=None, observacao=None):
    """Entrada, saída ou ajuste — sempre com registro do movimento."""
    peca = db.session.get(Peca, peca_id)
    if not peca:
        raise ErroNegocio("Peça não encontrada no estoque.")
    quantidade = float(quantidade or 0)
    if quantidade <= 0:
        raise ErroNegocio("Informe uma quantidade maior que zero.")

    # O saldo é alterado por um UPDATE condicional, não lido-e-regravado em
    # Python: se duas pessoas derem baixa da mesma peça no mesmo instante, o
    # banco resolve a disputa e a segunda recebe "estoque insuficiente".
    if tipo == "entrada":
        preco = float(custo_unitario or peca.custo_unitario or 0)
        db.session.execute(text("""
            UPDATE pecas
               SET custo_unitario = CASE
                       WHEN COALESCE(quantidade, 0) + :qtd > 0
                       THEN ROUND(CAST((COALESCE(quantidade, 0) * COALESCE(custo_unitario, 0)
                                   + :qtd * :preco) / (COALESCE(quantidade, 0) + :qtd)
                                  AS numeric), 2)
                       ELSE :preco END,
                   quantidade = COALESCE(quantidade, 0) + :qtd
             WHERE id = :id"""), {"qtd": quantidade, "preco": preco, "id": peca.id})
    elif tipo == "saida":
        resultado = db.session.execute(text("""
            UPDATE pecas
               SET quantidade = COALESCE(quantidade, 0) - :qtd
             WHERE id = :id AND COALESCE(quantidade, 0) >= :qtd"""),
            {"qtd": quantidade, "id": peca.id})
        if resultado.rowcount == 0:
            db.session.refresh(peca)
            raise ErroNegocio(f"Estoque insuficiente de {peca.codigo}: "
                              f"disponível {peca.quantidade:g} {peca.unidade}.")
    else:  # ajuste — define o saldo informado
        db.session.execute(text("UPDATE pecas SET quantidade = :qtd WHERE id = :id"),
                           {"qtd": quantidade, "id": peca.id})

    db.session.refresh(peca)

    db.session.add(MovimentoEstoque(
        peca_id=peca.id, tipo=tipo, quantidade=quantidade,
        custo_unitario=float(custo_unitario or peca.custo_unitario or 0),
        ordem_servico_id=os_id, documento=documento, observacao=observacao))
    return peca


def baixar_item_os(item: ItemOS):
    """Ao aplicar uma peça na OS o estoque é debitado uma única vez."""
    if item.peca_id and not item.baixado_estoque:
        movimentar_estoque(item.peca_id, "saida", item.quantidade,
                           item.valor_unitario, os_id=item.ordem_servico_id,
                           observacao="Aplicada na OS")
        item.baixado_estoque = True


def marcar_pneu_substituido(item: ItemOS):
    """Quando um item de pneu é aplicado numa posição da OS, o pneu que
    estava 'Em uso' naquela posição do veículo sai de circulação.

    Sem isso, o cadastro de Pneus (Módulo 7) — de onde vem o alerta de
    sulco baixo — nunca fica sabendo que a troca aconteceu: a OS e o
    cadastro de Pneus são registros separados, e trocar o pneu só pela OS
    não atualiza o pneu antigo. O alerta continuava ativo mesmo depois do
    serviço feito.
    """
    if not item.posicao_pneu:
        return
    ordem = db.session.get(OrdemServico, item.ordem_servico_id)
    if not ordem or not ordem.veiculo_id:
        return
    antigo = (Pneu.query
              .filter(Pneu.veiculo_id == ordem.veiculo_id,
                      Pneu.posicao == item.posicao_pneu,
                      Pneu.status == "Em uso")
              .first())
    if antigo:
        antigo.status = "Descartado"
        item.pneu_substituido_id = antigo.id


def reverter_pneu_substituido(item: ItemOS):
    """Desfaz o que marcar_pneu_substituido fez, quando o item de troca é

    removido da OS antes de qualquer outra coisa acontecer com o pneu: o
    pneu antigo volta a "Em uso" na posição, e o alerta de sulco baixo
    volta a aparecer se ele ainda estiver com sulco insuficiente.

    Só reverte se o pneu ainda estiver "Descartado" — se alguém já mexeu
    manualmente no cadastro dele (por exemplo, deu baixa definitiva), essa
    reversão automática não pisa em cima da decisão manual.
    """
    if not item.pneu_substituido_id:
        return
    pneu = db.session.get(Pneu, item.pneu_substituido_id)
    if pneu and pneu.status == "Descartado":
        pneu.status = "Em uso"
    item.pneu_substituido_id = None


def desvincular_movimentos(os_id):
    """Solta o histórico de estoque antes de apagar a OS.

    Os movimentos continuam existindo (o estoque nunca perde rastro), mas
    deixam de apontar para uma ordem que não existe mais.
    """
    db.session.flush()
    (MovimentoEstoque.query
     .filter_by(ordem_servico_id=os_id)
     .update({"ordem_servico_id": None, "observacao": "OS excluída"},
             synchronize_session=False))


def devolver_item_os(item: ItemOS):
    if item.peca_id and item.baixado_estoque:
        movimentar_estoque(item.peca_id, "entrada", item.quantidade,
                           item.valor_unitario, os_id=item.ordem_servico_id,
                           observacao="Devolvida da OS")
        item.baixado_estoque = False


# ---------------------------------------------------- notas fiscais de entrada
def _documento_nf(nota: NotaFiscal):
    return f"NF {nota.numero}" + (f"/{nota.serie}" if nota.serie else "")


def finalizar_nota_fiscal(nota: NotaFiscal):
    """Dá entrada no estoque de cada item lançado e trava a nota.

    A consulta dos itens é feita diretamente no banco antes da validação.
    Isso evita que uma coleção de relacionamento carregada anteriormente
    como vazia faça o sistema ignorar itens que já foram persistidos.
    """
    if nota.status != "Aberta":
        raise ErroNegocio("Esta nota já foi finalizada ou está cancelada.")

    db.session.flush()
    itens = (ItemNotaFiscal.query
             .filter_by(nota_fiscal_id=nota.id)
             .order_by(ItemNotaFiscal.id)
             .all())
    if not itens:
        raise ErroNegocio("Lance ao menos um item antes de finalizar a nota.")

    for item in itens:
        movimentar_estoque(item.peca_id, "entrada", item.quantidade, item.valor_unitario,
                           documento=_documento_nf(nota),
                           observacao=f"Entrada pela nota fiscal {nota.numero}")
        item.baixado_estoque = True
    nota.status = "Finalizada"
    nota.data_entrada = hoje()


def estornar_nota_fiscal(nota: NotaFiscal):
    """Reverte uma nota finalizada: tira do estoque o que ela havia dado entrada."""
    if nota.status != "Finalizada":
        raise ErroNegocio("Só é possível estornar uma nota finalizada.")
    itens = (ItemNotaFiscal.query
             .filter_by(nota_fiscal_id=nota.id)
             .order_by(ItemNotaFiscal.id)
             .all())
    for item in itens:
        if item.baixado_estoque:
            movimentar_estoque(item.peca_id, "saida", item.quantidade, item.valor_unitario,
                               documento=f"Estorno {_documento_nf(nota)}",
                               observacao=f"Estorno da nota fiscal {nota.numero}")
            item.baixado_estoque = False
    nota.status = "Cancelada"


# ------------------------------------------------------------- manutenção
def proximo_numero_os():
    """Gera o próximo número da OS sem correr o risco de dois iguais.

    No PostgreSQL, um bloqueio de transação garante que duas aberturas
    simultâneas não peguem o mesmo número; no SQLite a própria gravação já
    é serializada.
    """
    if db.engine.dialect.name.startswith("postgres"):
        db.session.execute(text("SELECT pg_advisory_xact_lock(918273)"))
    ano = hoje().year
    ultimo = (OrdemServico.query
              .filter(OrdemServico.numero.like(f"OS{ano}%"))
              .order_by(OrdemServico.numero.desc()).first())
    sequencia = int(ultimo.numero[-5:]) + 1 if ultimo else 1
    return f"OS{ano}{sequencia:05d}"


def sincronizar_status_veiculo(os_obj: OrdemServico):
    """Veículo entra em manutenção quando há OS aberta e volta ao encerrar."""
    veiculo = db.session.get(Veiculo, os_obj.veiculo_id)
    if not veiculo:
        return
    abertas = (OrdemServico.query
               .filter(OrdemServico.veiculo_id == veiculo.id,
                       OrdemServico.status != "Finalizada")
               .count())
    if abertas and veiculo.situacao != "Inativo":
        veiculo.situacao = "Em manutenção"
    elif veiculo.situacao == "Em manutenção":
        veiculo.situacao = "Disponível"

    if os_obj.status == "Finalizada":
        if not os_obj.data_fechamento:
            os_obj.data_fechamento = hoje()
        if os_obj.tipo == "Preventiva":
            veiculo.data_ultima_preventiva = os_obj.data_fechamento
        if os_obj.km_veiculo:
            # Identifica troca de óleo pela descrição da OS OU pelas peças
            # aplicadas (ex.: "Óleo motor 15W40"). Antes exigia também que o
            # campo "Grupo" estivesse marcado como "Motor" — como esse campo
            # não é obrigatório no formulário, muitas OS de troca de óleo
            # ficavam sem marcar o grupo e o alerta nunca era limpo, mesmo
            # com o serviço já feito.
            textos = f"{os_obj.descricao or ''}".lower()
            textos += " " + " ".join((i.descricao or "") for i in os_obj.itens).lower()
            if "óleo" in textos or "oleo" in textos:
                veiculo.km_ultima_troca_oleo = os_obj.km_veiculo
        if os_obj.km_veiculo and os_obj.km_veiculo > (veiculo.hodometro or 0):
            veiculo.hodometro = os_obj.km_veiculo
