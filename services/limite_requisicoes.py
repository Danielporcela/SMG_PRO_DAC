"""Trava de quantidade de requisições por IP, com bloqueio de 30 minutos.

Protege o SGMF contra robôs e ataques de força bruta/varredura. Funciona
em memória (sem banco e sem dependência nova), então não deixa nenhuma
requisição mais lenta: cada checagem é só uma conta em um dicionário.

Três regras, todas por IP do visitante:

  1. LOGIN   — tentativas em /login, /esqueci-senha e /redefinir-senha.
               Padrão: 10 em 5 minutos.
  2. VARREDURA — muitos 404 seguidos (robô procurando /wp-admin, /.env,
               /phpmyadmin...). Padrão: 25 em 1 minuto.
  3. GERAL   — total de requisições (páginas e APIs). Padrão: 600 em 1 minuto.

Estourou qualquer uma: o IP fica bloqueado por 30 minutos (HTTP 429, com
o cabeçalho Retry-After). Depois disso, volta ao normal sozinho.

Tudo pode ser ajustado por variável de ambiente no Render, sem mexer no
código (ver LIMITE_* abaixo). IPs de confiança (ex.: o IP fixo da empresa)
podem ser liberados em LIMITE_IPS_LIBERADOS="200.1.2.3,200.1.2.4".

Observação: o gunicorn roda com 2 processos (Procfile) e cada um guarda a
sua própria contagem; na prática o limite efetivo pode chegar a 2x o
configurado. Para contagem única entre processos seria preciso Redis.
"""
import os
import threading
import time
from collections import deque

from flask import Response, jsonify, request

# ---------------------------------------------------------------- ajustes
BLOQUEIO_SEGUNDOS = int(os.environ.get("LIMITE_BLOQUEIO_SEGUNDOS", 30 * 60))

LOGIN_MAX = int(os.environ.get("LIMITE_LOGIN_MAX", 10))
LOGIN_JANELA = int(os.environ.get("LIMITE_LOGIN_JANELA", 300))

VARREDURA_MAX = int(os.environ.get("LIMITE_404_MAX", 25))
VARREDURA_JANELA = int(os.environ.get("LIMITE_404_JANELA", 60))

GERAL_MAX = int(os.environ.get("LIMITE_GERAL_MAX", 600))
GERAL_JANELA = int(os.environ.get("LIMITE_GERAL_JANELA", 60))

ATIVO = os.environ.get("LIMITE_ATIVO", "1") == "1"
IPS_LIBERADOS = {ip.strip() for ip in
                 os.environ.get("LIMITE_IPS_LIBERADOS", "127.0.0.1,::1").split(",")
                 if ip.strip()}

# Caminhos que nunca contam nem são bloqueados (verificação do Render e
# arquivos estáticos — o bloqueio do IP, esse sim, vale até para eles).
_IGNORAR_CONTAGEM = ("/static/", "/saude", "/favicon.ico")
_ROTAS_LOGIN = ("/login", "/esqueci-senha", "/redefinir-senha")

_trava = threading.Lock()
_janelas = {}            # (regra, ip) -> deque de instantes
_bloqueados = {}         # ip -> instante em que o bloqueio termina
_motivos = {}            # ip -> texto do motivo (para o log)
_ultima_limpeza = 0.0


def ip_do_visitante():
    """IP real do visitante.

    Usa request.remote_addr, que o ProxyFix (app.py) já ajusta para o IP
    visto pelo proxy do Render. NÃO usa o cabeçalho X-Forwarded-For
    diretamente: o valor mais à esquerda é escrito pelo próprio cliente,
    e um robô poderia trocá-lo a cada requisição para fugir do bloqueio.
    """
    return request.remote_addr or ""


def _limpar(agora):
    """Remove contagens e bloqueios vencidos (no máximo 1x por minuto)."""
    global _ultima_limpeza
    if agora - _ultima_limpeza < 60:
        return
    _ultima_limpeza = agora
    for ip in [i for i, fim in _bloqueados.items() if fim <= agora]:
        _bloqueados.pop(ip, None)
        _motivos.pop(ip, None)
    janela_maior = max(LOGIN_JANELA, VARREDURA_JANELA, GERAL_JANELA)
    for chave in list(_janelas):
        fila = _janelas[chave]
        if not fila or fila[-1] < agora - janela_maior:
            _janelas.pop(chave, None)


def _contar(regra, ip, maximo, janela, agora):
    """Registra 1 evento e devolve True se o IP passou do limite da regra."""
    fila = _janelas.setdefault((regra, ip), deque())
    corte = agora - janela
    while fila and fila[0] < corte:
        fila.popleft()
    fila.append(agora)
    return len(fila) > maximo


def _bloquear(ip, motivo, agora):
    _bloqueados[ip] = agora + BLOQUEIO_SEGUNDOS
    _motivos[ip] = motivo
    # Zera as contagens do IP: ao fim dos 30 minutos ele começa do zero.
    for regra in ("login", "varredura", "geral"):
        _janelas.pop((regra, ip), None)
    print(f"[SGMF] IP {ip} bloqueado por {BLOQUEIO_SEGUNDOS // 60} min — {motivo}")


def _resposta_bloqueio(segundos):
    minutos = max(1, (segundos + 59) // 60)
    mensagem = (f"Muitas requisições deste endereço. Acesso bloqueado "
                f"temporariamente — tente novamente em cerca de {minutos} min.")
    if request.path.startswith("/api/") or request.is_json \
            or request.headers.get("X-Requested-With"):
        resposta = jsonify({"erro": mensagem})
    else:
        resposta = Response(
            f"<!doctype html><meta charset='utf-8'><title>Acesso bloqueado</title>"
            f"<body style='font-family:Arial,sans-serif;text-align:center;"
            f"margin-top:15vh'><h2>Acesso bloqueado temporariamente</h2>"
            f"<p>{mensagem}</p></body>", mimetype="text/html")
    resposta.status_code = 429
    resposta.headers["Retry-After"] = str(max(1, segundos))
    return resposta


# --------------------------------------------------------------- ganchos
def _antes_da_requisicao():
    if not ATIVO:
        return None
    ip = ip_do_visitante()
    if not ip or ip in IPS_LIBERADOS:
        return None

    agora = time.monotonic()
    with _trava:
        _limpar(agora)

        fim = _bloqueados.get(ip)
        if fim:
            if fim > agora:
                return _resposta_bloqueio(int(fim - agora))
            _bloqueados.pop(ip, None)
            _motivos.pop(ip, None)

        if request.path.startswith(_IGNORAR_CONTAGEM):
            return None

        if request.method == "POST" and request.path.startswith(_ROTAS_LOGIN):
            if _contar("login", ip, LOGIN_MAX, LOGIN_JANELA, agora):
                _bloquear(ip, f"mais de {LOGIN_MAX} tentativas de login/senha "
                              f"em {LOGIN_JANELA // 60} min", agora)
                return _resposta_bloqueio(BLOQUEIO_SEGUNDOS)

        if _contar("geral", ip, GERAL_MAX, GERAL_JANELA, agora):
            _bloquear(ip, f"mais de {GERAL_MAX} requisições em {GERAL_JANELA}s", agora)
            return _resposta_bloqueio(BLOQUEIO_SEGUNDOS)
    return None


def _depois_da_requisicao(resposta):
    """Conta os 404: robôs de varredura erram dezenas de endereços seguidos."""
    if not ATIVO or resposta.status_code != 404:
        return resposta
    if request.path.startswith(_IGNORAR_CONTAGEM):
        return resposta
    ip = ip_do_visitante()
    if not ip or ip in IPS_LIBERADOS:
        return resposta
    agora = time.monotonic()
    with _trava:
        if _contar("varredura", ip, VARREDURA_MAX, VARREDURA_JANELA, agora):
            _bloquear(ip, f"mais de {VARREDURA_MAX} endereços inexistentes "
                          f"(404) em {VARREDURA_JANELA}s", agora)
    return resposta


def registrar_limite(app):
    """Liga a trava na aplicação. Chamar uma vez, logo após criar o app,
    antes dos demais before_request (assim ela roda primeiro)."""
    app.before_request(_antes_da_requisicao)
    app.after_request(_depois_da_requisicao)


def bloqueios_ativos():
    """Lista [(ip, segundos_restantes, motivo)] — útil para diagnóstico."""
    agora = time.monotonic()
    with _trava:
        return [(ip, int(fim - agora), _motivos.get(ip, ""))
                for ip, fim in _bloqueados.items() if fim > agora]
