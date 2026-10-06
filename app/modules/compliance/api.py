from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import text

from app.core.audit.audit_service import audit
from app.core.security.crypto import normalize_id
from app.core.security.rbac import permission_required
from app.extensions import db

bp = Blueprint("compliance", __name__)


@bp.get("/alerts")
@permission_required("lcft:alert_read")
def alerts():
    status = request.args.get("status", "OPEN").upper()
    rows = db.session.execute(text(
        "SELECT id, rule_code, severity, entity_type, entity_id, score, message, status, created_at FROM engine.findings "
        "WHERE rule_code LIKE 'LCFT-%' AND status=:s ORDER BY score DESC LIMIT 200"), {"s": status}).all()
    audit("LCFT_ALERTS_VIEWED", entity_type="lcft", entity_id=status, metadata={"n": len(rows)}, request_id=g.request_id)  # el acceso a LC/FT se registra
    return jsonify(alerts=[dict(r._mapping) for r in rows])


@bp.post("/alerts/<int:fid>/status")
@permission_required("lcft:alert_manage")
def alert_status(fid):
    d = request.get_json(silent=True) or {}
    new, reason = str(d.get("status", "")).upper(), str(d.get("reason", "")).strip()
    if new not in ("IN_REVIEW", "ESCALATED", "CLOSED_FP", "CLOSED_RESOLVED"):
        return jsonify(error="Estado inválido"), 400
    if len(reason) < 10:
        return jsonify(error="Documente la decisión (mínimo 10 caracteres)"), 400
    r = db.session.execute(text("UPDATE engine.findings SET status=:s, assigned_to=CAST(:u AS uuid), "
                                "closed_by=CASE WHEN :c THEN CAST(:u AS uuid) END, closed_reason=CASE WHEN :c THEN :r END "
                                "WHERE id=:i AND rule_code LIKE 'LCFT-%'"),
                           {"s": new, "u": get_jwt_identity(), "c": new.startswith("CLOSED"), "r": reason, "i": fid})
    db.session.commit()
    if r.rowcount == 0:
        return jsonify(error="No encontrada"), 404
    audit("LCFT_ALERT_" + new, entity_type="finding", entity_id=str(fid), metadata={"reason": reason}, request_id=g.request_id)
    return jsonify(status=new)


@bp.post("/watchlist")
@permission_required("lcft:rule_configure", step_up=True)
def add_watchlist():
    d = request.get_json(silent=True) or {}
    doc, name = normalize_id(str(d.get("doc_id", ""))), str(d.get("list_name", "")).strip()
    if len(doc) < 6 or not name:
        return jsonify(error="Identificador o nombre de lista inválido"), 400
    db.session.execute(text("INSERT INTO compliance.watchlist (list_name, doc_id_norm, full_name, added_by) "
                            "VALUES (:l, :d, :n, CAST(:u AS uuid))"),
                       {"l": name, "d": doc, "n": d.get("full_name"), "u": get_jwt_identity()})
    db.session.commit()
    audit("WATCHLIST_ENTRY_ADDED", entity_type="watchlist", entity_id=doc[:3] + "***", metadata={"list": name}, request_id=g.request_id)
    return jsonify(status="OK"), 201


@bp.get("/watchlist")
@permission_required("lcft:alert_read")
def list_watchlist():
    rows = db.session.execute(text("SELECT id, list_name, doc_id_norm, full_name, added_at, active FROM compliance.watchlist "
                                   "ORDER BY added_at DESC LIMIT 200")).all()
    out = [{**dict(r._mapping), "doc_id_norm": r.doc_id_norm[:3] + "*" * max(len(r.doc_id_norm) - 3, 0)} for r in rows]  # enmascarado
    return jsonify(watchlist=out)


@bp.post("/watchlist/<int:wid>/deactivate")
@permission_required("lcft:rule_configure", step_up=True)
def deactivate_watchlist(wid):
    r = db.session.execute(text("UPDATE compliance.watchlist SET active=false WHERE id=:i AND active"), {"i": wid})
    db.session.commit()
    if r.rowcount == 0:
        return jsonify(error="No encontrada"), 404
    audit("WATCHLIST_ENTRY_DEACTIVATED", entity_type="watchlist", entity_id=str(wid), request_id=g.request_id)
    return jsonify(status="INACTIVE")
