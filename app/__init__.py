import uuid
from datetime import date, datetime
from decimal import Decimal

from flask import Flask, g, request
from flask.json.provider import DefaultJSONProvider


class SicasJSON(DefaultJSONProvider):
    """Fechas en ISO 8601 y NUMERIC como número (no como texto)."""

    @staticmethod
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        return DefaultJSONProvider.default(o)


CSP = {
    "default-src": "'self'",
    "script-src": "'self'",
    "style-src": "'self'",
    "connect-src": "'self'",
    "img-src": ["'self'", "data:"],
    "frame-ancestors": "'none'",
    "object-src": "'none'",
}


def create_app(config=None) -> Flask:
    """SICAS — Sistema Integral de Contraloría y Auditoría de Seguros."""
    # Imports diferidos: permite importar app.core / app.modules (tests, scripts)
    # sin exigir variables de entorno ni todas las extensiones de Flask.
    from .config import BaseConfig
    from .extensions import cors, db, jwt, limiter, talisman

    config = config or BaseConfig
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.json = SicasJSON(app)
    app.config.from_object(config)

    db.init_app(app)
    jwt.init_app(app)
    limiter.init_app(app)
    cors.init_app(
        app,
        origins=app.config["CORS_ORIGINS"],
        supports_credentials=True,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-TOKEN"],
    )
    talisman.init_app(
        app,
        force_https=app.config.get("FORCE_HTTPS", True),
        strict_transport_security=True,
        strict_transport_security_max_age=31536000,
        strict_transport_security_include_subdomains=True,
        content_security_policy=CSP,
        referrer_policy="no-referrer",
        frame_options="DENY",
    )

    @app.before_request
    def _request_context():
        incoming = request.headers.get("X-Request-ID", "")
        try:
            g.request_id = str(uuid.UUID(incoming))
        except ValueError:
            g.request_id = str(uuid.uuid4())

    @app.after_request
    def _extra_headers(resp):
        resp.headers["X-Request-ID"] = g.request_id
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        return resp

    _register_jwt_callbacks(app, jwt)

    from .api.v1 import register_blueprints

    register_blueprints(app)

    from .tasks.celery_app import make_celery

    make_celery(app)          # la API encola tareas: necesita el broker configurado igual que el worker
    return app


def _register_jwt_callbacks(app: Flask, jwt) -> None:
    import redis

    r = redis.from_url(app.config["RATELIMIT_STORAGE_URI"])

    @jwt.token_in_blocklist_loader
    def _is_revoked(_header, payload):
        return r.exists(f"jwt:revoked:{payload['jti']}") == 1
