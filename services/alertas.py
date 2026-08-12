"""Motor de alertas do SGMF Pro.

Os alertas são derivados do estado atual dos cadastros. Assim, quando a causa
é corrigida, o alerta deixa de aparecer imediatamente. O ControleTarefa guarda
somente o ciclo de vida necessário para avisar quando um alerta nasce ou é
sanado, sem transformar alertas antigos em pendências permanentes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from flask import current_app
from extensions import db
from models import (Abastecimento, ControleTarefa, Motorista, OrdemServico, Peca,
                    Pneu, Veiculo)
from services.tempo import agora, hoje


PREFIXO_ESTADO = "alerta:"


def _cfg(nome, padrao):
    return current_app.config.get(nome, padrao)


def _alerta(chave, categoria, severidade, titulo, mensagem, entidade, entidade_id,
            destino=None):
    return {
        "id": chave,
        "chave": chave,
        "categoria": categoria,
        "severidade": severidade,
        "titulo": titulo,
        "mensagem": mensagem,
        "entidade": entidade,
        "entidade_id": entidade_id,
        "destino": destino,
        "ativo": True,
        "sanado": False,
    }


def listar_alertas_ativos():
    """Calcula somente as condições que continuam exigindo ação agora."""
    data = hoje()
    alertas = []
    aviso_oleo = float(_cfg("KM_AVISO_TROCA_OLEO", 500))
    aviso_preventiva = int(_cfg("ALERTA_PREVENTIVA_DIAS", 30))
    aviso_cnh = int(_cfg("ALERTA_CNH_DIAS", 30))
    sulco_minimo = float(_cfg("SULCO_MINIMO_MM", 4.0))
    desvio_consumo = float(_cfg("DESVIO_CONSUMO_ALERTA", 0.15))

    for v in Veiculo.query.filter(Veiculo.ativo.is_(True)).all():
        proxima = float(v.km_proxima_troca_oleo or 0)
        atual = float(v.hodometro or 0)
        restante = proxima - atual
        if proxima > 0 and restante <= aviso_oleo:
            if restante <= 0:
                sev = "critico"
                titulo = "Troca de óleo vencida"
                msg = f"{v.prefixo} está {abs(restante):.0f} km além do limite da troca de óleo."
            else:
                sev = "atencao"
                titulo = "Troca de óleo próxima"
                msg = f"{v.prefixo} está a {restante:.0f} km da próxima troca de óleo."
            alertas.append(_alerta(
                f"oleo:veiculo:{v.id}", "oleo", sev, titulo, msg,
                "veiculo", v.id, "/veiculos"))

        if v.data_ultima_preventiva:
            vencimento = v.data_ultima_preventiva + timedelta(days=int(v.intervalo_preventiva_dias or 90))
            faltam = (vencimento - data).days
            if faltam <= aviso_preventiva:
                if faltam < 0:
                    sev = "critico"
                    titulo = "Preventiva vencida"
                    msg = f"{v.prefixo} está com a preventiva vencida há {abs(faltam)} dia(s)."
                else:
                    sev = "atencao"
                    titulo = "Preventiva próxima"
                    msg = f"{v.prefixo} tem preventiva prevista em {faltam} dia(s)."
                alertas.append(_alerta(
                    f"preventiva:veiculo:{v.id}", "preventiva", sev, titulo, msg,
                    "veiculo", v.id, "/manutencao"))
        elif int(v.intervalo_preventiva_dias or 0) > 0:
            alertas.append(_alerta(
                f"preventiva:veiculo:{v.id}", "preventiva", "atencao",
                "Preventiva sem registro",
                f"{v.prefixo} ainda não possui data de última preventiva registrada.",
                "veiculo", v.id, "/manutencao"))

    for m in Motorista.query.filter(Motorista.ativo.is_(True)).all():
        if not m.validade_cnh:
            continue
        faltam = (m.validade_cnh - data).days
        if faltam <= aviso_cnh:
            if faltam < 0:
                sev = "critico"
                titulo = "CNH vencida"
                msg = f"A CNH de {m.nome} venceu há {abs(faltam)} dia(s)."
            else:
                sev = "atencao"
                titulo = "CNH próxima do vencimento"
                msg = f"A CNH de {m.nome} vence em {faltam} dia(s)."
            alertas.append(_alerta(
                f"cnh:motorista:{m.id}", "cnh", sev, titulo, msg,
                "motorista", m.id, "/motoristas"))

    for p in Peca.query.filter(Peca.quantidade <= Peca.estoque_minimo).all():
        alertas.append(_alerta(
            f"estoque:peca:{p.id}", "estoque", "atencao",
            "Estoque mínimo atingido",
            f"{p.codigo} · {p.descricao}: saldo {p.quantidade or 0:g}, mínimo {p.estoque_minimo or 0:g}.",
            "peca", p.id, "/estoque"))

    for p in Pneu.query.filter(Pneu.status == "Em uso", Pneu.sulco_mm < sulco_minimo).all():
        veiculo = p.veiculo.prefixo if p.veiculo else "veículo não informado"
        alertas.append(_alerta(
            f"pneu:{p.id}", "pneu", "critico", "Pneu abaixo do sulco mínimo",
            f"Pneu {p.numero_fogo} de {veiculo} está com {p.sulco_mm or 0:g} mm de sulco.",
            "pneu", p.id, "/pneus"))

    for os_obj in OrdemServico.query.filter(
            OrdemServico.status != "Finalizada",
            OrdemServico.prioridade.in_(["Alta", "Crítica"])).all():
        sev = "critico" if os_obj.prioridade == "Crítica" else "atencao"
        numero = os_obj.numero or f"OS {os_obj.id}"
        alertas.append(_alerta(
            f"os:prioridade:{os_obj.id}", "ordem_servico", sev,
            "Ordem de serviço prioritária",
            f"{numero} está {os_obj.status.lower()} com prioridade {os_obj.prioridade.lower()}.",
            "ordem_servico", os_obj.id, "/manutencao"))

    # Consumo: compara o abastecimento mais recente com a média histórica
    # anterior do mesmo veículo. O alerta some quando o consumo volta ao padrão.
    if desvio_consumo > 0:
        veiculos_ids = [v.id for v in Veiculo.query.filter(Veiculo.ativo.is_(True)).all()]
        for vid in veiculos_ids:
            regs = (Abastecimento.query
                    .filter(Abastecimento.veiculo_id == vid,
                            Abastecimento.km_por_litro > 0)
                    .order_by(Abastecimento.data.desc(), Abastecimento.id.desc())
                    .limit(7).all())
            if len(regs) < 4:
                continue
            atual = float(regs[0].km_por_litro or 0)
            historico = [float(r.km_por_litro or 0) for r in regs[1:] if (r.km_por_litro or 0) > 0]
            if not historico:
                continue
            media = sum(historico) / len(historico)
            limite = media * (1 - desvio_consumo)
            if atual < limite:
                v = regs[0].veiculo
                ident = v.prefixo if v else f"Veículo {vid}"
                alertas.append(_alerta(
                    f"consumo:veiculo:{vid}", "consumo", "atencao",
                    "Consumo fora do padrão",
                    f"{ident} registrou {atual:.2f} km/l contra média recente de {media:.2f} km/l.",
                    "veiculo", vid, "/combustivel"))

    ordem = {"critico": 0, "atencao": 1, "informativo": 2}
    alertas.sort(key=lambda a: (ordem.get(a["severidade"], 9), a["titulo"], a["chave"]))
    return alertas


def _nome_tarefa(chave):
    digest = hashlib.sha1(chave.encode("utf-8")).hexdigest()[:32]
    return f"{PREFIXO_ESTADO}{digest}"


def _decodificar(raw):
    if not raw:
        return {}
    try:
        valor = json.loads(raw)
        return valor if isinstance(valor, dict) else {}
    except Exception:
        return {}


def _codificar(status, notificado, chave, titulo, categoria):
    payload = {
        "s": status,
        "n": int(notificado),
        "k": str(chave or "")[:70],
        "t": str(titulo or "")[:100],
        "c": str(categoria or "")[:30],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def sincronizar_estados():
    """Reconcilia ativos com o histórico e detecta o que acabou de ser sanado."""
    ativos = listar_alertas_ativos()
    por_tarefa = {_nome_tarefa(a["chave"]): a for a in ativos}
    existentes = {
        r.tarefa: r for r in ControleTarefa.query.filter(
            ControleTarefa.tarefa.like(f"{PREFIXO_ESTADO}%")).all()
    }
    abertos = []
    sanados = []
    momento = agora()
    data = hoje()

    for tarefa, alerta in por_tarefa.items():
        registro = existentes.get(tarefa)
        if registro is None:
            registro = ControleTarefa(
                tarefa=tarefa,
                ultima_execucao=data,
                ultimo_resultado=_codificar(
                    "ativo", 0, alerta["chave"], alerta["titulo"], alerta["categoria"]),
                atualizado_em=momento,
            )
            db.session.add(registro)
            abertos.append(alerta)
            continue

        anterior = _decodificar(registro.ultimo_resultado)
        mudou = anterior.get("s") != "ativo"
        notificado = 0 if mudou else int(anterior.get("n", 0))
        registro.ultima_execucao = data
        registro.atualizado_em = momento
        registro.ultimo_resultado = _codificar(
            "ativo", notificado, alerta["chave"], alerta["titulo"], alerta["categoria"])
        if mudou:
            abertos.append(alerta)

    for tarefa, registro in existentes.items():
        if tarefa in por_tarefa:
            continue
        anterior = _decodificar(registro.ultimo_resultado)
        if anterior.get("s") != "ativo":
            continue
        evento = {
            "id": anterior.get("k") or tarefa,
            "chave": anterior.get("k") or tarefa,
            "categoria": anterior.get("c") or "geral",
            "severidade": "informativo",
            "titulo": anterior.get("t") or "Alerta sanado",
            "mensagem": "A condição que originou este alerta não está mais presente.",
            "ativo": False,
            "sanado": True,
            "tarefa": tarefa,
        }
        registro.atualizado_em = momento
        registro.ultimo_resultado = _codificar(
            "sanado", 0, evento["chave"], evento["titulo"], evento["categoria"])
        sanados.append(evento)

    db.session.commit()
    return {"ativos": ativos, "abertos": abertos, "sanados": sanados}


def reservar_eventos_notificacao():
    """Reserva mudanças de estado de modo atômico para evitar e mails duplicados."""
    eventos = []
    registros = ControleTarefa.query.filter(
        ControleTarefa.tarefa.like(f"{PREFIXO_ESTADO}%")).all()
    for registro in registros:
        estado = _decodificar(registro.ultimo_resultado)
        if int(estado.get("n", 0)) != 0 or estado.get("s") not in ("ativo", "sanado"):
            continue
        raw_antigo = registro.ultimo_resultado
        raw_reservado = _codificar(
            estado.get("s"), 2, estado.get("k"), estado.get("t"), estado.get("c"))
        atualizados = (ControleTarefa.query
                       .filter(ControleTarefa.id == registro.id,
                               ControleTarefa.ultimo_resultado == raw_antigo)
                       .update({"ultimo_resultado": raw_reservado,
                                "atualizado_em": agora()},
                               synchronize_session=False))
        db.session.commit()
        if atualizados != 1:
            continue
        eventos.append({
            "tarefa": registro.tarefa,
            "status": estado.get("s"),
            "chave": estado.get("k"),
            "titulo": estado.get("t"),
            "categoria": estado.get("c"),
        })
    return eventos


def concluir_notificacao(eventos, sucesso=True):
    alvo = 1 if sucesso else 0
    nomes = [e.get("tarefa") for e in eventos if e.get("tarefa")]
    if not nomes:
        return
    for registro in ControleTarefa.query.filter(ControleTarefa.tarefa.in_(nomes)).all():
        estado = _decodificar(registro.ultimo_resultado)
        if int(estado.get("n", 0)) != 2:
            continue
        registro.ultimo_resultado = _codificar(
            estado.get("s"), alvo, estado.get("k"), estado.get("t"), estado.get("c"))
        registro.atualizado_em = agora()
    db.session.commit()


def obter_resumo():
    estado = sincronizar_estados()
    ativos = estado["ativos"]
    return {
        "total": len(ativos),
        "criticos": sum(1 for a in ativos if a["severidade"] == "critico"),
        "atencao": sum(1 for a in ativos if a["severidade"] == "atencao"),
        "alertas": ativos,
        "sanados_agora": estado["sanados"],
    }


# Nomes alternativos para manter compatibilidade com versões anteriores.
gerar_alertas = listar_alertas_ativos
coletar_alertas = listar_alertas_ativos
alertas_ativos = listar_alertas_ativos
listar_alertas = listar_alertas_ativos
