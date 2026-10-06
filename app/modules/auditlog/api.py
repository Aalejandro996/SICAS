"""Consulta del audit trail (solo lectura) y verificación de su integridad."""
import os

from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy import create_engine, text

from app.core.audit.audit_service import audit
from app.core.security.rbac import permission_required

bp = Blueprint("auditlog", __name__)
_engine = None


def _reader():
    """Conexión de SOLO LECTURA al audit trail. En producción: AUDIT_READER_DATABASE_URL (rol audit_reader)."""
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ.get("AUDIT_READER_DATABASE_URL") or current_app.config["SQLALCHEMY_DATABASE_URI"],
                                pool_pre_ping=True)
    return _engine


@bp.get("")
@permission_required("auditlog:read")
def list_events():
    a = request.args
    limit = min(max(int(a.get("limit", 100)), 1), 500)
    offset = max(int(a.get("offset", 0)), 0)
    where, params = ["1=1"], {"lim": limit, "off": offset}
    for col, arg in (("action", "action"), ("outcome", "outcome"), ("entity_type", "entity_type"), ("actor_username", "actor")):
        if a.get(arg):
            where.append(f"{col} = :{arg}")
            params[arg] = a[arg]
    if a.get("entity_id"):
        where.append("entity_id = :entity_id"); params["entity_id"] = a["entity_id"]
    if a.get("desde"):
        where.append("occurred_at >= CAST(:desde AS timestamptz)"); params["desde"] = a["desde"]
    if a.get("hasta"):
        where.append("occurred_at < CAST(:hasta AS timestamptz)"); params["hasta"] = a["hasta"]
    sql = ("SELECT id, occurred_at, actor_username, actor_roles, action, entity_type, entity_id, outcome, "
           "host(ip_address) AS ip, metadata FROM audit.audit_log WHERE " + " AND ".join(where) +
           " ORDER BY id DESC LIMIT :lim OFFSET :off")        # los nombres de columna salen de una lista fija
    with _reader().connect() as cx:
        rows = [dict(r._mapping) for r in cx.execute(text(sql), params)]
    audit("AUDITLOG_VIEWED", entity_type="audit_log", metadata={"filtros": {k: v for k, v in a.items() if k != "offset"}}, request_id=g.request_id)
    return jsonify(events=rows, limit=limit, offset=offset)


@bp.get("/actions")
@permission_required("auditlog:read")
def list_actions():
    with _reader().connect() as cx:
        rows = cx.execute(text("SELECT DISTINCT action FROM audit.audit_log ORDER BY 1")).all()
    return jsonify(actions=[r.action for r in rows])


@bp.post("/verify")
@permission_required("auditlog:verify_chain", step_up=True)
def verify():
    with _reader().connect() as cx:
        broken = [{"id": r.broken_id, "motivo": r.reason} for r in cx.execute(text("SELECT broken_id, reason FROM audit.verify_chain()"))]
        total = cx.execute(text("SELECT count(*) FROM audit.audit_log")).scalar()
    audit("AUDITLOG_VERIFIED", outcome="SUCCESS" if not broken else "FAILURE", entity_type="audit_log",
          metadata={"filas": total, "inconsistentes": len(broken)}, request_id=g.request_id)
    return jsonify(rows_checked=total, ok=not broken, inconsistencies=broken[:100])
