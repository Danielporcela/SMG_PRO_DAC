"""Ajustes de velocidade do SGMF que não mudam telas, rotas nem regras.

Três coisas, todas "por fora" do código existente:

  1. COMPRESSÃO (gzip) de HTML, JSON, CSS e JS. A página trafega bem menos
     bytes, o que pesa muito em celular e em rede lenta.
  2. CACHE DOS ARQUIVOS ESTÁTICOS. Todo url_for('static', ...) ganha
     automaticamente ?v=<data do arquivo>. Enquanto o arquivo não muda, o
     navegador guarda por 1 ano e nem pergunta ao servidor; quando o arquivo
     muda (novo deploy), o ?v= muda e o navegador baixa de novo sozinho.
  3. CACHE CURTO (30 s) dos números do Painel. Os endpoints de leitura do
     dashboard fazem várias consultas ao PostgreSQL; repetir a mesma
     consulta do mesmo usuário em até 30 s devolve a resposta pronta.
     Qualquer gravação (POST/PUT/PATCH/DELETE) limpa o cache, e o usuário
     que gravou nunca recebe resposta antiga.

Ajustes por variável de ambiente (opcionais):
  DASH_CACHE_SEGUNDOS=30   (0 desliga só o cache do painel)
  GZIP_ATIVO=1             (0 desliga a compressão)
"""
import gzip
import os
import threading
import time

from flask import Response, g, request, session

# ------------------------------------------------------------------ ajustes
GZIP_ATIVO = os.environ.get("GZIP_ATIVO", "1") == "1"
GZIP_MINIMO_BYTES = 600
DASH_CACHE_SEGUNDOS = int(os.environ.get("DASH_CACHE_SEGUNDOS", 30))
DASH_CACHE_MAX_ITENS = 300

_UM_ANO = 31536000
_COMPRIMIVEIS = ("text/", "application/json", "application/javascript",
                 "application/xml", "image/svg+xml")

# Somente leituras do Painel. "conectados" fica de fora de propósito: precisa
# ser em tempo real.
_ROTAS_PAINEL = {
    "/api/painel/resumo",
    "/api/painel/graficos",
    "/api/painel/combustivel-diario",
    "/api/painel/horas-mecanicos",
    "/api/painel/consumo-frotas",
    "/api/painel/alertas",
    "/api/combustivel/estoque-resumo",
}
_METODOS_LEITURA = ("GET", "HEAD", "OPTIONS")


# ------------------------------------------------- 1 e 2: estáticos + gzip
def _registrar_estaticos_e_gzip(app):
    versoes = {}

    @app.url_defaults
    def versionar_estaticos(endpoint, values):
        """Acrescenta ?v=<mtime> em todo link de /static (sem mexer nos templates)."""
        if endpoint != "static" or "v" in values:
            return
        nome = values.get("filename")
        if not nome:
            return
        v = versoes.get(nome)
        if v is None:
            try:
                v = int(os.stat(os.path.join(app.static_folder, nome)).st_mtime)
            except OSError:
                return
            if not app.debug:           # em produção o arquivo só muda no deploy
                versoes[nome] = v
        values["v"] = v

    gz_estaticos = {}                   # (caminho, etag) -> bytes comprimidos
    trava = threading.Lock()

    @app.after_request
    def cache_e_compressao(resposta):
        # --- cache do navegador para /static
        if request.path.startswith("/static/") and resposta.status_code in (200, 304):
            if request.args.get("v"):
                resposta.headers["Cache-Control"] = f"public, max-age={_UM_ANO}, immutable"
            else:
                resposta.headers["Cache-Control"] = "public, max-age=600"

        # --- gzip
        if not GZIP_ATIVO or request.method != "GET" or resposta.status_code != 200:
            return resposta
        if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
            return resposta
        if resposta.headers.get("Content-Encoding") or resposta.is_streamed and \
                not request.path.startswith("/static/"):
            return resposta
        tipo = (resposta.mimetype or "").lower()
        if not tipo.startswith(_COMPRIMIVEIS):
            return resposta

        estatico = request.path.startswith("/static/")
        if resposta.direct_passthrough:
            if not estatico:            # downloads/anexos: não mexer
                return resposta
            resposta.direct_passthrough = False

        etag = resposta.get_etag()[0]
        chave = (request.path, etag) if (estatico and etag) else None
        if chave:
            with trava:
                dados_gz = gz_estaticos.get(chave)
        else:
            dados_gz = None

        if dados_gz is None:
            dados = resposta.get_data()
            if len(dados) < GZIP_MINIMO_BYTES:
                return resposta
            dados_gz = gzip.compress(dados, compresslevel=6, mtime=0)
            if chave:
                with trava:
                    if len(gz_estaticos) > 200:
                        gz_estaticos.clear()
                    gz_estaticos[chave] = dados_gz

        resposta.set_data(dados_gz)     # atualiza o Content-Length
        resposta.headers["Content-Encoding"] = "gzip"
        resposta.vary.add("Accept-Encoding")
        if etag:                        # o corpo comprimido é outra representação
            resposta.set_etag(etag, weak=True)
        return resposta


# --------------------------------------------------- 3: cache curto do painel
def _registrar_cache_painel(app):
    cache = {}                          # chave -> (vence_em, corpo, mimetype)
    trava = threading.Lock()

    def _chave():
        uid = session.get("usuario_id")
        if not uid:
            return None
        # _dash_v muda quando ESTE usuário grava algo: as respostas guardadas
        # antes da gravação deixam de valer para ele (vale entre os 2 processos
        # do gunicorn, pois a marca viaja no cookie de sessão).
        return (uid, session.get("_dash_v", 0), request.path,
                request.query_string)

    @app.before_request
    def servir_do_cache():
        if DASH_CACHE_SEGUNDOS <= 0 or request.method != "GET" \
                or request.path not in _ROTAS_PAINEL:
            return None
        chave = _chave()
        if not chave:
            return None
        with trava:
            item = cache.get(chave)
        if not item or item[0] < time.monotonic():
            return None
        g._painel_do_cache = True
        resposta = Response(item[1], status=200, mimetype=item[2])
        resposta.headers["X-SGMF-Cache"] = "HIT"
        return resposta

    @app.after_request
    def guardar_ou_limpar(resposta):
        if DASH_CACHE_SEGUNDOS <= 0:
            return resposta

        # Gravou algo com sucesso: esvazia o cache e invalida o do próprio usuário.
        if request.method not in _METODOS_LEITURA and resposta.status_code < 400:
            with trava:
                cache.clear()
            if session.get("usuario_id"):
                session["_dash_v"] = int(time.time() * 1000)
            return resposta

        if (request.method == "GET" and request.path in _ROTAS_PAINEL
                and resposta.status_code == 200 and not resposta.direct_passthrough
                and not getattr(g, "_painel_do_cache", False)
                and (resposta.mimetype or "").endswith("json")):
            chave = _chave()
            if chave:
                corpo = resposta.get_data()
                agora = time.monotonic()
                with trava:
                    if len(cache) >= DASH_CACHE_MAX_ITENS:
                        for k in [k for k, v in cache.items() if v[0] < agora]:
                            cache.pop(k, None)
                        if len(cache) >= DASH_CACHE_MAX_ITENS:
                            cache.clear()
                    cache[chave] = (agora + DASH_CACHE_SEGUNDOS, corpo,
                                    resposta.mimetype)
        return resposta


# ------------------------------------------------------------- ligação
def registrar_desempenho(app):
    """Compressão e cache de estáticos. Chamar logo no início de criar_app."""
    _registrar_estaticos_e_gzip(app)


def registrar_cache_painel(app):
    """Cache curto do painel. Chamar no FIM de criar_app, depois de todos os
    before_request (login, presença, permissões), para que eles continuem
    rodando antes de qualquer resposta guardada ser devolvida."""
    _registrar_cache_painel(app)
