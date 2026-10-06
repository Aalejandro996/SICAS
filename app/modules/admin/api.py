import uuid

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.core.audit.audit_service import audit
from app.core.security.rbac import permission_required
from app.modules.auth.password import Argon2Hasher

from .repositories import SqlAdminRepo
from .service import AdminError, UserAdminService

bp = Blueprint("admin", __name__)
_STATUS = {"NOT_FOUND": 404, "FORBIDDEN": 403, "DUPLICATE": 409, "PENDING_EXISTS": 409, "NOT_PENDING": 409,
           "DUAL_CONTROL": 403, "SELF_CHANGE": 403, "SOD_VIOLATION": 409, "LAST_ADMIN": 409}


def _svc() -> UserAdminService:
    return UserAdminService(SqlAdminRepo(), Argon2Hasher(), audit, lambda: str(uuid.uuid4()))


def _guard(fn):
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except AdminError as e:
            return jsonify(error=e.message, code=e.code), _STATUS.get(e.code, 400)
    wrapper.__name__ = fn.__name__
    return wrapper


@bp.get("/users")
@permission_required("user:read")
def list_users():
    return jsonify(users=SqlAdminRepo().list_users())


@bp.post("/users")
@permission_required("user:create", step_up=True)
@_guard
def create_user():
    d = request.get_json(silent=True) or {}
    uid, temp = _svc().create_user(get_jwt_identity(), str(d.get("username", "")), str(d.get("email", "")), str(d.get("full_name", "")))
    return jsonify(id=uid, temporary_password=temp, note="Se muestra una sola vez; deberá cambiarla al ingresar."), 201


@bp.post("/users/<uuid:uid>/deactivate")
@permission_required("user:deactivate", step_up=True)
@_guard
def deactivate(uid):
    _svc().set_active(get_jwt_identity(), str(uid), False)
    return jsonify(status="INACTIVE")


@bp.post("/users/<uuid:uid>/activate")
@permission_required("user:deactivate", step_up=True)
@_guard
def activate(uid):
    _svc().set_active(get_jwt_identity(), str(uid), True)
    return jsonify(status="ACTIVE")


@bp.post("/users/<uuid:uid>/unlock")
@permission_required("user:unlock")
@_guard
def unlock(uid):
    _svc().unlock(get_jwt_identity(), str(uid))
    return jsonify(status="UNLOCKED")


@bp.post("/users/<uuid:uid>/reset-mfa")
@permission_required("user:reset_mfa", step_up=True)
@_guard
def reset_mfa(uid):
    _svc().reset_mfa(get_jwt_identity(), str(uid))
    return jsonify(status="MFA_RESET")


def _request_role_for_user(target_user_id: str):
    d = request.get_json(silent=True) or {}
    rid = _svc().request_role_change(
        get_jwt_identity(), target_user_id, str(d.get("role", "")),
        str(d.get("action", "GRANT")).upper(), str(d.get("reason", ""))
    )
    return jsonify(request_id=rid, status="PENDING"), 201


@bp.post("/role-requests")
@permission_required("role:assign")
@_guard
def request_role():
    d = request.get_json(silent=True) or {}
    return _request_role_for_user(str(d.get("user_id", "")))


# Ruta explícita para la pantalla de usuarios. Mantiene exactamente el mismo
# flujo de doble control, pero evita depender de un user_id enviado en el body.
@bp.post("/users/<uuid:uid>/role-request")
@permission_required("role:assign")
@_guard
def request_role_for_user(uid):
    return _request_role_for_user(str(uid))


@bp.get("/role-requests")
@permission_required("role:read", "role:approve", "role:assign")
def list_requests():
    return jsonify(requests=SqlAdminRepo().list_requests(request.args.get("status", "PENDING").upper()))


@bp.post("/role-requests/<uuid:rid>/decision")
@permission_required("role:approve", step_up=True)
@_guard
def decide(rid):
    d = request.get_json(silent=True) or {}
    _svc().decide_role_request(get_jwt_identity(), g.claims.get("roles", []), str(rid), bool(d.get("approve")), str(d.get("note", "")))
    return jsonify(status="APPROVED" if d.get("approve") else "REJECTED")


# ------------------------------------------------------------------ roles, parámetros, respaldos, salud
import json as _json
import os as _os

from sqlalchemy import text

from app.extensions import db
from .params import ParamError, SPECS as PARAM_SPECS, defaults as param_defaults, validate_param


@bp.get("/roles")
@permission_required("role:read", "role:assign")
def roles():
    from app.core.security.permissions import ROLES
    return jsonify(roles=[{"code": c, "description": d} for c, d in ROLES.items()])


@bp.get("/params")
@permission_required("param:read")
def get_params():
    saved = {r.key: r.value for r in db.session.execute(text("SELECT key, value FROM admin.system_params"))}
    return jsonify(params={**param_defaults(), **saved}, editable=list(PARAM_SPECS))


@bp.put("/params/<key>")
@permission_required("param:update", step_up=True)
def put_param(key):
    try:
        value = validate_param(key, (request.get_json(silent=True) or {}).get("value"))
    except ParamError as e:
        return jsonify(error=str(e)), 400
    old = db.session.execute(text("SELECT value FROM admin.system_params WHERE key=:k"), {"k": key}).scalar()
    db.session.execute(text("INSERT INTO admin.system_params (key, value, updated_by) VALUES (:k, CAST(:v AS jsonb), CAST(:u AS uuid)) "
                            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_by=EXCLUDED.updated_by, updated_at=now()"),
                       {"k": key, "v": _json.dumps(value), "u": get_jwt_identity()})
    db.session.commit()
    audit("PARAM_UPDATED", entity_type="param", entity_id=key, before_data={"value": old}, after_data={"value": value}, request_id=g.request_id)
    return jsonify(status="OK", value=value)


@bp.get("/backups")
@permission_required("backup:read")
def list_backups():
    rows = db.session.execute(text("SELECT id::text, started_at, finished_at, status, size_bytes, sha256, error FROM admin.backups "
                                   "ORDER BY started_at DESC LIMIT 30")).all()
    return jsonify(backups=[dict(r._mapping) for r in rows])


@bp.post("/backups")
@permission_required("backup:run", step_up=True)
def run_backup_now():
    from app.tasks.admin_tasks import run_backup
    bid = str(uuid.uuid4())
    db.session.execute(text("INSERT INTO admin.backups (id, requested_by) VALUES (CAST(:i AS uuid), CAST(:u AS uuid))"),
                       {"i": bid, "u": get_jwt_identity()})
    db.session.commit()
    audit("BACKUP_REQUESTED", entity_type="backup", entity_id=bid, request_id=g.request_id)
    run_backup.apply_async(args=[bid], queue="reports")
    return jsonify(id=bid, status="RUNNING"), 202


@bp.get("/system/health")
@permission_required("health:read")
def system_health():
    """Estado de la plataforma: base de datos, Redis, colas y cargas atascadas. No expone secretos ni rutas."""
    from flask import current_app
    out = {}
    try:
        out["database"] = {
            "status": "ok",
            "size_mb": round(db.session.execute(text("SELECT pg_database_size(current_database())")).scalar() / 1048576, 1),
            "connections": db.session.execute(text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")).scalar()}
    except Exception:  # noqa: BLE001
        out["database"] = {"status": "error"}
    try:
        import redis
        broker = redis.from_url(current_app.config["CELERY_BROKER_URL"])
        broker.ping()
        out["redis"] = {"status": "ok", "queues": {q: broker.llen(q) for q in ("ingestion", "reports", "alerts")}}
    except Exception:  # noqa: BLE001
        out["redis"] = {"status": "error"}
    out["celery_mode"] = "eager (sin worker)" if current_app.config.get("CELERY_EAGER") else "worker"
    stuck = db.session.execute(text("SELECT count(*) FROM insurance.ingestion_jobs WHERE status IN ('QUEUED','PROCESSING') "
                                    "AND created_at < now() - interval '10 minutes'")).scalar()
    out["ingestion_stuck"] = stuck
    out["integrity_failures_24h"] = db.session.execute(text(
        "SELECT count(*) FROM audit.audit_log WHERE action='AUDIT_INTEGRITY_FAILURE' AND occurred_at > now() - interval '24 hours'")).scalar() \
        if _can_read_audit() else None
    return jsonify(out)


def _can_read_audit() -> bool:
    from flask import current_app
    return current_app.config.get("ENV") == "dev"       # en producción la app no tiene SELECT sobre audit_log
