"""Camada de segurança para qualquer app WSGI (Flask, Django...).
NÃO altera o código original: apenas envolve o app e ajusta as respostas.
Variáveis opcionais no Render: APP_MODULE (padrão "app:app") e CSP."""
import os, importlib

_mod, _, _obj = os.environ.get("APP_MODULE", "app:app").partition(":")
_app = getattr(importlib.import_module(_mod), _obj or "app")

SEC = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": os.environ.get("CSP",
        "default-src 'self'; img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'"),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def _cookie(v):
    attrs = [a.strip().lower() for a in v.split(";")]
    if "secure" not in attrs:
        v += "; Secure"
    if "httponly" not in attrs:
        v += "; HttpOnly"
    if not any(a.startswith("samesite") for a in attrs):
        v += "; SameSite=Lax"
    return v


def application(environ, start_response):
    # O Render termina o HTTPS no proxy; informa ao app que a conexão original é segura.
    if environ.get("HTTP_X_FORWARDED_PROTO") == "https":
        environ["wsgi.url_scheme"] = "https"

    def sr(status, headers, exc_info=None):
        out, present = [], set()
        for k, v in headers:
            lk = k.lower()
            if lk in ("server", "x-powered-by"):
                continue
            if lk == "set-cookie":
                v = _cookie(v)
            present.add(lk)
            out.append((k, v))
        out += [(k, v) for k, v in SEC.items() if k.lower() not in present]
        return start_response(status, out, exc_info)

    return _app(environ, sr)
