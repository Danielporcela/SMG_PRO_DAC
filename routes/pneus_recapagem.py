"""API do ciclo do pneu: retirados da frota, recapagem com nota fiscal e descarte."""
from flask import Blueprint, jsonify, request, session

from extensions import db
from models import Fornecedor, Pneu
from services.crud import ErroNegocio, editar_tela, registrar_log, visualizar_tela

from services.recapagem_pneus import (STATUS_DESCARTADO, STATUS_EM_RECAPAGEM, STATUS_ESTOQUE,
                                      STATUS_RETIRADO, NotaRecapagem, PneuCiclo,
                                      numero_recapagem, proxima_vida, registrar_ciclo,
                                      ultimo_evento)
from services.tempo import hoje, ler_data

bp_pneus_recapagem = Blueprint("pneus_recapagem", __name__, url_prefix="/api")


def _usuario():
    return session.get("usuario_nome", "sistema")


def _historico(pneu, evento, detalhe):
    """Usa o histórico que o mapa de pneus já tem (import tardio evita ciclo)."""
    from routes.api import _registrar_historico_pneu
    _registrar_historico_pneu(pneu, evento if evento in ("Troca", "Instalação", "Rodízio") else "Atualização",
                              detalhe)


def _linha(p):
    """Linha das listas de retirados/descartados."""
    retirada = ultimo_evento(p.id, "Retirada")
    envio = ultimo_evento(p.id, "Envio recapagem")
    descarte = ultimo_evento(p.id, "Descarte")
    d = {
        "id": p.id, "numero_fogo": p.numero_fogo, "marca": p.marca, "medida": p.medida,
        "vida": p.vida, "recapagens": numero_recapagem(p.vida), "status": p.status,
        "sulco_mm": p.sulco_mm, "km_pneu": p.km_pneu,
        "retirada_data": retirada.data.isoformat() if retirada and retirada.data else None,
        "veiculo_rotulo": retirada.veiculo_rotulo if retirada else None,
        "posicao": retirada.posicao if retirada else None,
        "os_numero": retirada.ordem_servico_numero if retirada else None,
        "envio_data": envio.data.isoformat() if envio and envio.data else None,
        "envio_fornecedor": envio.fornecedor_nome if envio else None,
    }
    if descarte is not None:
        d.update({"descarte_data": descarte.data.isoformat() if descarte.data else None,
                  "descarte_motivo": descarte.motivo, "descarte_nota": descarte.nota_numero,
                  "descarte_fornecedor": descarte.fornecedor_nome,
                  "descarte_origem": "Recusado na recapagem" if descarte.nota_id else "Descartado direto"})
    return d


# ------------------------------------------------------------------ listas
@bp_pneus_recapagem.get("/pneus-retirados")
@visualizar_tela("pneus")
def listar_retirados():
    """Pneus retirados da frota (aguardando decisão) e os que estão na recapadora."""
    pneus = (Pneu.query.filter(Pneu.status.in_((STATUS_RETIRADO, STATUS_EM_RECAPAGEM)))
             .order_by(Pneu.numero_fogo).all())
    return jsonify([_linha(p) for p in pneus])


@bp_pneus_recapagem.get("/pneus-descartados")
@visualizar_tela("pneus")
def listar_descartados():
    pneus = Pneu.query.filter(Pneu.status == STATUS_DESCARTADO).order_by(Pneu.numero_fogo).all()
    linhas = [_linha(p) for p in pneus]
    linhas.sort(key=lambda l: l.get("descarte_data") or "", reverse=True)
    return jsonify(linhas)


@bp_pneus_recapagem.get("/pneus/<int:pneu_id>/ciclo")
@visualizar_tela("pneus")
def ciclo_do_pneu(pneu_id):
    pneu = db.get_or_404(Pneu, pneu_id)
    eventos = (PneuCiclo.query.filter_by(pneu_id=pneu.id)
               .order_by(PneuCiclo.id.asc()).all())
    return jsonify({"pneu": _linha(pneu), "eventos": [e.to_dict() for e in eventos]})


# ------------------------------------------------------ enviar à recapadora
@bp_pneus_recapagem.post("/pneus-retirados/enviar-recapagem")
@editar_tela("pneus")
def enviar_recapagem():
    dados = request.get_json(silent=True) or {}
    try:
        ids = [int(i) for i in (dados.get("pneu_ids") or [])]
        if not ids:
            raise ErroNegocio("Selecione ao menos um pneu retirado.")
        data = ler_data(dados.get("data"), "data de envio") or hoje()
        forn = None
        if dados.get("fornecedor_id") not in (None, ""):
            forn = db.session.get(Fornecedor, int(dados["fornecedor_id"]))
        for pid in ids:
            p = db.session.get(Pneu, pid)
            if p is None or p.status != STATUS_RETIRADO:
                raise ErroNegocio("Só pneus da lista de retirados podem ser enviados à recapagem.")
            p.status = STATUS_EM_RECAPAGEM
            registrar_ciclo(p, "Envio recapagem", data=data, usuario=_usuario(),
                            fornecedor_nome=forn.nome if forn else None)
            _historico(p, "Atualização", "Enviado para recapagem" + (f" ({forn.nome})." if forn else "."))
        registrar_log("editar", "pneus", ids[0], f"{len(ids)} pneu(s) enviados à recapagem")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True, "enviados": len(ids)})


# ------------------------------------------------------- descarte direto
@bp_pneus_recapagem.post("/pneus-retirados/<int:pneu_id>/descartar")
@editar_tela("pneus")
def descartar_retirado(pneu_id):
    dados = request.get_json(silent=True) or {}
    try:
        p = db.get_or_404(Pneu, pneu_id)
        if p.status not in (STATUS_RETIRADO, STATUS_EM_RECAPAGEM):
            raise ErroNegocio("Só pneus retirados ou em recapagem podem ser descartados aqui.")
        motivo = str(dados.get("motivo") or "").strip()[:300] or None
        p.status = STATUS_DESCARTADO
        registrar_ciclo(p, "Descarte", data=ler_data(dados.get("data"), "data do descarte") or hoje(),
                        usuario=_usuario(), motivo=motivo)
        _historico(p, "Atualização", "Descartado" + (f": {motivo}" if motivo else "."))
        registrar_log("editar", "pneus", p.id, f"Pneu {p.numero_fogo} descartado")
        db.session.commit()
    except ErroNegocio as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    return jsonify({"ok": True})


# ------------------------------------------- NF de retorno da recapagem
@bp_pneus_recapagem.get("/recapagem/notas")
@visualizar_tela("pneus")
def listar_notas_recapagem():
    notas = NotaRecapagem.query.order_by(NotaRecapagem.id.desc()).limit(200).all()
    saida = []
    for n in notas:
        itens = PneuCiclo.query.filter_by(nota_id=n.id).order_by(PneuCiclo.id).all()
        saida.append(n.to_dict(itens))
    return jsonify(saida)


@bp_pneus_recapagem.post("/recapagem/notas")
@editar_tela("pneus")
def lancar_nota_recapagem():
    """Lança a NF de retorno. Cada item é um número de fogo e seu resultado:

    "Recapado"   -> volta ao Estoque com a vida seguinte (1ª, 2ª... recapagem)
    "Descartado" -> vai para a lista de descarte
    """
    dados = request.get_json(silent=True) or {}
    try:
        numero = str(dados.get("numero") or "").strip()
        if not numero:
            raise ErroNegocio("Informe o número da nota fiscal.")
        itens = dados.get("itens") or []
        if not itens:
            raise ErroNegocio("Informe ao menos um número de fogo na nota.")

        forn = None
        if dados.get("fornecedor_id") not in (None, ""):
            forn = db.session.get(Fornecedor, int(dados["fornecedor_id"]))
        data_emissao = ler_data(dados.get("data_emissao"), "data de emissão")

        nota = NotaRecapagem(
            numero=numero, serie=str(dados.get("serie") or "").strip()[:10] or None,
            data_emissao=data_emissao, data_entrada=hoje(),
            fornecedor_id=forn.id if forn else None, fornecedor_nome=forn.nome if forn else None,
            observacao=str(dados.get("observacao") or "").strip()[:300] or None,
            usuario=_usuario())
        db.session.add(nota)
        db.session.flush()

        vistos = set()
        for it in itens:
            fogo = str(it.get("numero_fogo") or "").strip().upper()
            if not fogo:
                raise ErroNegocio("Há um item sem número de fogo.")
            if fogo in vistos:
                raise ErroNegocio(f"O nº de fogo {fogo} aparece duas vezes na nota.")
            vistos.add(fogo)
            p = Pneu.query.filter(Pneu.numero_fogo == fogo).first()
            if p is None:
                raise ErroNegocio(f"Pneu {fogo} não cadastrado.")
            if p.status not in (STATUS_RETIRADO, STATUS_EM_RECAPAGEM):
                raise ErroNegocio(f"O pneu {fogo} não está na lista de retirados "
                                  f"(status atual: {p.status}).")
            resultado = str(it.get("resultado") or "Recapado").strip()
            if resultado not in ("Recapado", "Descartado"):
                raise ErroNegocio(f"Resultado inválido para o pneu {fogo}.")
            try:
                valor = float(str(it.get("valor") or 0).replace(",", ".") or 0)
            except ValueError:
                raise ErroNegocio(f"Valor inválido no pneu {fogo}.")
            motivo = str(it.get("motivo") or "").strip()[:300] or None

            if resultado == "Recapado":
                p.vida = proxima_vida(p.vida)
                p.status = STATUS_ESTOQUE
                p.veiculo_id = None
                p.posicao = None
                if valor:
                    p.custo = valor
                registrar_ciclo(p, "Retorno recapagem", data=data_emissao or hoje(),
                                usuario=_usuario(), nota_id=nota.id, nota_numero=nota.to_dict()["identificacao"],
                                fornecedor_nome=nota.fornecedor_nome, valor=valor or None, motivo=motivo)
                _historico(p, "Atualização",
                           f"Voltou da recapagem ({p.vida}) na {nota.to_dict()['identificacao']}; em Estoque.")
            else:
                p.status = STATUS_DESCARTADO
                registrar_ciclo(p, "Descarte", data=data_emissao or hoje(),
                                usuario=_usuario(), nota_id=nota.id, nota_numero=nota.to_dict()["identificacao"],
                                fornecedor_nome=nota.fornecedor_nome, valor=valor or None,
                                motivo=motivo or "Recusado na recapagem")
                _historico(p, "Atualização",
                           f"Recusado na recapagem ({nota.to_dict()['identificacao']}); descartado.")

        registrar_log("criar", "notas_recapagem_pneu", nota.id,
                      f"{nota.to_dict()['identificacao']} · {len(vistos)} pneu(s)")
        db.session.commit()
    except (ErroNegocio, ValueError) as e:
        db.session.rollback()
        return jsonify({"erro": str(e)}), 400
    itens_nota = PneuCiclo.query.filter_by(nota_id=nota.id).order_by(PneuCiclo.id).all()
    return jsonify(nota.to_dict(itens_nota)), 201
