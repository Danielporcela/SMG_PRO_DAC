"""Cálculos automáticos disparados quando um registro é salvo."""
from datetime import date

from flask import has_request_context, session
from sqlalchemy import text

from services.tempo import hoje

from extensions import db
from models import (Abastecimento, ItemOS, ItemOSPecaSerial, MovimentoEstoque,
                    MovimentoPecaSerial, OrdemServico, Peca, PecaSerial, Veiculo)
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
                       documento=None, observacao=None, usuario_id=None, usuario_nome=None,
                       grupo_consumo_id=None):
    """Entrada, saída ou ajuste com registro do movimento e do responsável."""
    if has_request_context():
        if usuario_id is None:
            usuario_id = session.get("usuario_id")
        if not usuario_nome:
            usuario_nome = session.get("usuario_nome")
    if not usuario_nome:
        usuario_nome = "Sistema"
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
        ordem_servico_id=os_id, documento=documento, observacao=observacao,
        usuario_id=usuario_id, usuario_nome=usuario_nome,
        grupo_consumo_id=grupo_consumo_id))
    return peca


def baixar_item_os(item: ItemOS):
    """Baixa o estoque pela quantidade lançada no item da OS.

    A chamada principal ocorre ao finalizar a ordem de serviço. O campo
    baixado_estoque impede que o mesmo item seja processado duas vezes.
    """
    if item.peca_id and not item.baixado_estoque:
        from services.grupos_consumo import grupo_para_ordem
        grupo = grupo_para_ordem(item.ordem_servico_id)
        grupo_consumo_id = grupo.id if grupo else None
        movimentar_estoque(item.peca_id, "saida", item.quantidade,
                           item.valor_unitario, os_id=item.ordem_servico_id,
                           observacao="Aplicada na OS",
                           grupo_consumo_id=grupo_consumo_id)
        item.baixado_estoque = True


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
    (MovimentoPecaSerial.query
     .filter_by(ordem_servico_id=os_id)
     .update({"ordem_servico_id": None, "observacao": "OS excluída"},
             synchronize_session=False))


def devolver_item_os(item: ItemOS):
    """Devolve ao estoque a peça removida de uma OS.

    Itens novos trabalham somente por quantidade. Para registros antigos que
    ainda possuam vínculos por número de série, preservamos a devolução legado
    sem somar o saldo duas vezes.
    """
    vinculos_legados = list(item.pecas_serial)
    if vinculos_legados:
        for vinculo in vinculos_legados:
            devolver_serial_ao_estoque(vinculo.peca_serial, motivo="Removida da OS")
            db.session.delete(vinculo)
        item.baixado_estoque = False
        return

    if item.peca_id and item.baixado_estoque:
        movimentar_estoque(item.peca_id, "entrada", item.quantidade,
                           item.valor_unitario, os_id=item.ordem_servico_id,
                           observacao="Devolvida da OS")
        item.baixado_estoque = False


# ------------------------------------------------- peças rastreadas por série
def _sincronizar_saldo_peca(peca_id):
    """Peca.quantidade é só um espelho da contagem de unidades 'Estoque' —
    mantido para os relatórios, alertas e telas antigas continuarem
    funcionando sem precisar recalcular tudo na hora.
    """
    peca = db.session.get(Peca, peca_id)
    if not peca:
        return
    peca.quantidade = (PecaSerial.query
                       .filter_by(peca_id=peca_id, status="Estoque").count())


def _registrar_movimento_serial(serial, tipo, veiculo_id=None, ordem_servico_id=None,
                                km_veiculo=None, observacao=None, usuario=None):
    if not usuario and has_request_context():
        usuario = session.get("usuario_nome")
    if not usuario:
        usuario = "Sistema"
    db.session.add(MovimentoPecaSerial(
        peca_serial_id=serial.id, tipo=tipo, veiculo_id=veiculo_id,
        ordem_servico_id=ordem_servico_id, km_veiculo=km_veiculo,
        observacao=observacao, usuario=usuario))


def dar_entrada_serial(peca_id, numero_serie, custo_unitario=0, origem="Cadastro manual",
                       documento=None, observacao=None, usuario=None):
    """Cria uma nova unidade rastreável (nº de série) já no estoque.

    Usada tanto no cadastro manual da peça quanto na finalização da nota
    fiscal — os dois pontos em que uma unidade pode "nascer" no sistema.
    """
    numero_serie = str(numero_serie or "").strip()
    if not numero_serie:
        raise ErroNegocio("Informe o número de série/identificação da peça.")
    if PecaSerial.query.filter_by(numero_serie=numero_serie).first():
        raise ErroNegocio(f"Já existe uma peça cadastrada com o número '{numero_serie}'.")
    serial = PecaSerial(peca_id=peca_id, numero_serie=numero_serie, status="Estoque",
                        custo_unitario=float(custo_unitario or 0), origem=origem,
                        documento_origem=documento, data_entrada=hoje())
    db.session.add(serial)
    db.session.flush()
    _registrar_movimento_serial(serial, "Entrada", observacao=observacao or documento,
                                usuario=usuario)
    _sincronizar_saldo_peca(peca_id)
    return serial


def instalar_serial_no_item(numero_serie, item: ItemOS, ordem: OrdemServico, usuario=None):
    """Vincula UMA unidade específica (já em estoque) a um item da OS.

    Marca a unidade como 'Em uso' no veículo da ordem e registra o
    movimento — é isso que depois permite rastrear "onde foi colocada"
    a peça de determinado número.
    """
    numero_serie = str(numero_serie or "").strip()
    if not numero_serie:
        raise ErroNegocio("Informe o número de série da peça a instalar.")
    serial = PecaSerial.query.filter_by(numero_serie=numero_serie).first()
    if not serial:
        raise ErroNegocio(f"Não existe nenhuma peça com o número '{numero_serie}' no sistema.")
    if item.peca_id and serial.peca_id != item.peca_id:
        raise ErroNegocio(f"O número '{numero_serie}' pertence a outra peça "
                          f"({serial.peca.codigo if serial.peca else '?'}), não a "
                          f"{item.peca.codigo if item.peca else ''}.")
    if serial.status != "Estoque":
        raise ErroNegocio(f"A peça '{numero_serie}' não está disponível no estoque "
                          f"(status atual: {serial.status}).")
    serial.status = "Em uso"
    serial.veiculo_atual_id = ordem.veiculo_id
    serial.ordem_servico_atual_id = ordem.id
    db.session.add(ItemOSPecaSerial(item_os_id=item.id, peca_serial_id=serial.id))
    _registrar_movimento_serial(serial, "Instalação", veiculo_id=ordem.veiculo_id,
                                ordem_servico_id=ordem.id, km_veiculo=ordem.km_veiculo,
                                observacao=f"Aplicada na OS {ordem.numero}", usuario=usuario)
    _sincronizar_saldo_peca(serial.peca_id)
    item.baixado_estoque = True
    return serial


def devolver_serial_ao_estoque(serial: PecaSerial, motivo="Removida da OS", usuario=None):
    """A unidade volta para 'Estoque' e fica disponível para ser
    reinstalada depois, em qualquer outro veículo — o histórico anterior
    não é apagado, só ganha mais uma linha.
    """
    ordem_id = serial.ordem_servico_atual_id
    serial.status = "Estoque"
    serial.veiculo_atual_id = None
    serial.ordem_servico_atual_id = None
    _registrar_movimento_serial(serial, "Remoção", ordem_servico_id=ordem_id,
                                observacao=motivo, usuario=usuario)
    _sincronizar_saldo_peca(serial.peca_id)


def descartar_serial(serial: PecaSerial, observacao=None, usuario=None):
    """Baixa definitiva de uma unidade (quebrou, foi descartada etc.)."""
    if serial.status == "Descartado":
        raise ErroNegocio(f"A peça '{serial.numero_serie}' já está descartada.")
    veiculo_id = serial.veiculo_atual_id
    ordem_id = serial.ordem_servico_atual_id
    serial.status = "Descartado"
    serial.veiculo_atual_id = None
    serial.ordem_servico_atual_id = None
    _registrar_movimento_serial(serial, "Descarte", veiculo_id=veiculo_id,
                                ordem_servico_id=ordem_id, observacao=observacao,
                                usuario=usuario)
    _sincronizar_saldo_peca(serial.peca_id)


def regularizar_seriais_peca(peca_id, numeros_serie, usuario=None):
    """Converte o saldo antigo (peça lançada antes do rastreio por série)
    em unidades individuais rastreáveis — uma só vez por peça.

    Exige que a quantidade de números informados bata exatamente com o
    saldo já existente no estoque dessa peça (contagem de PecaSerial com
    status 'Estoque' comparado com Peca.quantidade — para não duplicar
    saldo de peças que já foram parcialmente regularizadas).
    """
    peca = db.session.get(Peca, peca_id)
    if not peca:
        raise ErroNegocio("Peça não encontrada.")
    ja_regularizadas = PecaSerial.query.filter_by(peca_id=peca_id).count()
    pendente = int(round((peca.quantidade or 0))) - ja_regularizadas
    if pendente <= 0:
        raise ErroNegocio("Esta peça já está com o saldo todo regularizado.")
    if len(numeros_serie) != pendente:
        raise ErroNegocio(
            f"Informe exatamente {pendente} número(s) de série — é o saldo "
            f"ainda sem unidade individual cadastrada para esta peça.")
    criados = []
    for numero in numeros_serie:
        criados.append(dar_entrada_serial(
            peca_id, numero, peca.custo_unitario, origem="Regularização de saldo",
            documento="Regularização", observacao="Saldo existente antes do rastreio por série",
            usuario=usuario))
    return criados


# ------------------------------------------------------------- manutenção
def proximo_numero_os():
    """Gera o próximo número da OS sem correr o risco de dois iguais.

    Formato sequencial simples: 001, 002, 003... Os números antigos, no
    formato "OS2026000xx", não entram nessa contagem — a numeração nova
    recomeça do 001 e segue daí em diante, ignorando o histórico anterior.

    No PostgreSQL, um bloqueio de transação garante que duas aberturas
    simultâneas não peguem o mesmo número; no SQLite a própria gravação já
    é serializada.
    """
    if db.engine.dialect.name.startswith("postgres"):
        db.session.execute(text("SELECT pg_advisory_xact_lock(918273)"))
    maior = 0
    for (numero,) in db.session.query(OrdemServico.numero).all():
        if numero and numero.strip().isdigit():
            maior = max(maior, int(numero))
    return f"{maior + 1:03d}"


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
        if os_obj.grupo == "Motor" and os_obj.km_veiculo:
            # troca de óleo costuma ser lançada no grupo Motor
            textos = f"{os_obj.descricao or ''}".lower()
            if "óleo" in textos or "oleo" in textos:
                veiculo.km_ultima_troca_oleo = os_obj.km_veiculo
        if os_obj.km_veiculo and os_obj.km_veiculo > (veiculo.hodometro or 0):
            veiculo.hodometro = os_obj.km_veiculo
