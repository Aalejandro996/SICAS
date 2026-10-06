from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from app.extensions import db, limiter

bp = Blueprint("health", __name__)


@bp.get("/health")
@limiter.exempt
def health():
    return jsonify(status="ok", app="SICAS")


@bp.get("/health/ready")
@limiter.exempt
def ready():
    checks = {}
    try:
        db.session.execute(text("SELECT 1")); checks["database"] = "ok"
    except Exception:  # noqa: BLE001
        checks["database"] = "error"
    try:
        import redis
        redis.from_url(current_app.config["RATELIMIT_STORAGE_URI"]).ping(); checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "error"
    code = 200 if all(v == "ok" for v in checks.values()) else 503
    return jsonify(status="ready" if code == 200 else "degraded", checks=checks), code     # sin detalles internos
