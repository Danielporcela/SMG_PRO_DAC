import os
import importlib
from werkzeug.middleware.proxy_fix import ProxyFix

modulo, _, objeto = os.environ.get(
    "APP_MODULE", "app:app"
).partition(":")

application = getattr(
    importlib.import_module(modulo),
    objeto or "app"
)

application.wsgi_app = ProxyFix(
    application.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1
)
