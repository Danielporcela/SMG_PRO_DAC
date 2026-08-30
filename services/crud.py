"""Fábrica de rotas REST.

Em vez de repetir listar/criar/editar/excluir em cada módulo, cada rota
declara os campos que aceita e recebe a API pronta. Isso mantém o
comportamento igual em todo o sistema (validação, log, mensagens de erro).
"""
from datetime import date, datetime, time
from functools import wraps

from flask import jsonify, request, session

from extensions import db
from models import PADRAO_POR_PERFIL, PESO_NIVEL, LogAuditoria


# ----------------------------------------------------------------- segurança
def login_obrigatorio(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("usuario_id"):
            return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
        return f(*args, **kwargs)
    return wrapper


def perfil_obrigatorio(*perfis):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("usuario_id"):
                return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
            if session.get("perfil") not in perfis:
                return jsonify({"erro": "Seu perfil não permite esta ação."}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def pode_escrever(f):
    """Perfil 'consulta' apenas visualiza: não cria, não edita, não exclui.

    Mantido para as poucas rotas que não pertencem a nenhuma tela específica
    da matriz de permissões (ex.: trocar a própria senha). Rotas de módulo
    devem usar visualizar_tela()/editar_tela() abaixo.
    """
    return perfil_obrigatorio("admin", "operador")(f)


# --------------------------------------------------- permissão por tela
def nivel_na_tela(tela):
    """Nível de acesso do usuário logado na tela informada.

    Lê o mapa calculado no login (session['permissoes']); administrador
    sempre tem 'editar' em tudo, independente do mapa.
    """
    if session.get("perfil") == "admin":
        return "editar"
    return (session.get("permissoes") or {}).get(
        tela, PADRAO_POR_PERFIL.get(session.get("perfil"), "nenhum"))


def nivel_permite(tela, nivel_minimo="visualizar"):
    return PESO_NIVEL.get(nivel_na_tela(tela), 0) >= PESO_NIVEL.get(nivel_minimo, 1)


def _resposta_sem_permissao():
    return jsonify({"erro": "Seu perfil não autoriza esta ação nesta tela."}), 403


def visualizar_tela(tela):
    """Exige sessão ativa e nível 'visualizar' (ou 'editar') na tela indicada."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("usuario_id"):
                return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
            if not nivel_permite(tela, "visualizar"):
                return _resposta_sem_permissao()
            return f(*args, **kwargs)
        return wrapper
    return decorator


def editar_tela(tela):
    """Exige sessão ativa e nível 'editar' na tela indicada."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not session.get("usuario_id"):
                return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
            if not nivel_permite(tela, "editar"):
                return _resposta_sem_permissao()
            return f(*args, **kwargs)
        return wrapper
    return decorator


def checar_tela(tela, nivel_minimo="visualizar"):
    """Verificação avulsa para rotas cuja tela só é conhecida em tempo de
    execução (ex.: anexos, que atendem tanto 'ordens' quanto
    'abastecimentos'). Devolve a resposta 401/403 pronta, ou None se pode
    seguir.
    """
    if not session.get("usuario_id"):
        return jsonify({"erro": "Sessão expirada. Entre novamente."}), 401
    if not nivel_permite(tela, nivel_minimo):
        return _resposta_sem_permissao()
    return None


def registrar_log(acao, entidade, registro_id, detalhe=""):
    db.session.add(LogAuditoria(usuario=session.get("usuario_nome", "sistema"),
                                acao=acao, entidade=entidade,
                                registro_id=registro_id, detalhe=detalhe))


# ------------------------------------------------------------- conversores
def _converter(valor, tipo):
    if valor is None or valor == "":
        return None
    if tipo == "int":
        return int(float(valor))
    if tipo == "float":
        return float(str(valor).replace(",", "."))
    if tipo == "bool":
        return valor in (True, "true", "True", 1, "1", "on", "sim")
    if tipo == "date":
        if isinstance(valor, (date, datetime)):
            return valor if isinstance(valor, date) else valor.date()
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    if tipo == "time":
        if isinstance(valor, time):
            return valor
        # aceita "HH:MM" (input type=time) ou "HH:MM:SS"
        texto = str(valor).strip()[:8]
        formato = "%H:%M:%S" if texto.count(":") == 2 else "%H:%M"
        return datetime.strptime(texto, formato).time()
    return str(valor).strip()


def aplicar_campos(obj, dados, campos):
    """Copia apenas os campos declarados, convertendo o tipo."""
    for nome, tipo in campos.items():
        if nome in dados:
            try:
                setattr(obj, nome, _converter(dados.get(nome), tipo))
            except (ValueError, TypeError):
                raise ValueError(f"Valor inválido no campo '{nome}'.")
    return obj


class ErroNegocio(Exception):
    """Erro previsto de regra de negócio — vira mensagem amigável na tela."""


# -------------------------------------------------------------- fábrica
def registrar_crud(bp, rota, Model, campos, ordem=None, obrigatorios=(),
                   antes_salvar=None, depois_salvar=None, antes_excluir=None,
                   serializar=None, filtrar=None, tela=None):
    """`tela`, quando informado, liga as quatro rotas (listar/obter/criar/
    editar/excluir) à matriz de permissões: listar e obter exigem
    'visualizar'; criar, editar e excluir exigem 'editar'. Sem `tela`, cai
    no comportamento antigo (login_obrigatorio / pode_escrever) — usado só
    pela rota de usuários, que já tem sua própria proteção admin-only.
    """
    nome = rota.strip("/")
    ser = serializar or (lambda o: o.to_dict())
    protetor_leitura = visualizar_tela(tela) if tela else login_obrigatorio
    protetor_escrita = editar_tela(tela) if tela else pode_escrever

    @bp.get(f"/{nome}", endpoint=f"{nome}_listar")
    @protetor_leitura
    def _listar(Model=Model, ser=ser, ordem=ordem, filtrar=filtrar):
        q = Model.query
        if filtrar:
            try:
                q = filtrar(q, request.args)
            except ErroNegocio as e:
                return jsonify({"erro": str(e)}), 400
        if ordem is not None:
            q = q.order_by(ordem)
        return jsonify([ser(o) for o in q.all()])

    @bp.get(f"/{nome}/<int:registro_id>", endpoint=f"{nome}_obter")
    @protetor_leitura
    def _obter(registro_id, Model=Model, ser=ser):
        return jsonify(ser(db.get_or_404(Model, registro_id)))

    @bp.post(f"/{nome}", endpoint=f"{nome}_criar")
    @protetor_escrita
    def _criar(Model=Model, campos=campos, ser=ser, obrigatorios=obrigatorios,
               antes_salvar=antes_salvar, depois_salvar=depois_salvar, nome=nome):
        dados = request.get_json(silent=True) or {}
        faltando = [c for c in obrigatorios if not dados.get(c)]
        if faltando:
            return jsonify({"erro": "Preencha: " + ", ".join(faltando)}), 400
        obj = Model()
        try:
            aplicar_campos(obj, dados, campos)
            if antes_salvar:
                antes_salvar(obj, dados, None)
            db.session.add(obj)
            db.session.flush()
            if depois_salvar:
                depois_salvar(obj, dados, None)
            registrar_log("criar", nome, obj.id)
            db.session.commit()
        except (ValueError, ErroNegocio) as e:
            db.session.rollback()
            return jsonify({"erro": str(e)}), 400
        except Exception as e:  # violação de unicidade, FK inexistente etc.
            db.session.rollback()
            return jsonify({"erro": f"Não foi possível salvar: {e.__class__.__name__}. "
                                    "Verifique códigos duplicados e campos obrigatórios."}), 400
        return jsonify(ser(obj)), 201

    @bp.put(f"/{nome}/<int:registro_id>", endpoint=f"{nome}_editar")
    @protetor_escrita
    def _editar(registro_id, Model=Model, campos=campos, ser=ser,
                antes_salvar=antes_salvar, depois_salvar=depois_salvar, nome=nome):
        obj = db.get_or_404(Model, registro_id)
        dados = request.get_json(silent=True) or {}
        anterior = ser(obj)
        try:
            aplicar_campos(obj, dados, campos)
            if antes_salvar:
                antes_salvar(obj, dados, anterior)
            db.session.flush()
            if depois_salvar:
                depois_salvar(obj, dados, anterior)
            registrar_log("editar", nome, obj.id)
            db.session.commit()
        except (ValueError, ErroNegocio) as e:
            db.session.rollback()
            return jsonify({"erro": str(e)}), 400
        except Exception as e:
            db.session.rollback()
            return jsonify({"erro": f"Não foi possível salvar: {e.__class__.__name__}."}), 400
        return jsonify(ser(obj))

    @bp.delete(f"/{nome}/<int:registro_id>", endpoint=f"{nome}_excluir")
    @protetor_escrita
    def _excluir(registro_id, Model=Model, antes_excluir=antes_excluir, nome=nome):
        obj = db.get_or_404(Model, registro_id)
        try:
            if antes_excluir:
                antes_excluir(obj)
            db.session.delete(obj)
            registrar_log("excluir", nome, registro_id)
            db.session.commit()
        except ErroNegocio as e:
            db.session.rollback()
            return jsonify({"erro": str(e)}), 400
        except Exception:
            db.session.rollback()
            return jsonify({"erro": "Este registro está vinculado a outros lançamentos "
                                    "e não pode ser excluído."}), 400
        return jsonify({"ok": True})

