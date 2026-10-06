import uuid

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import text

from app.core.audit.audit_service import audit
from app.core.security.rbac import permission_required
from app.extensions import db

from .engine import REGISTRY

bp = Blueprint("audit_engine", __name__)
SEV = ("CRITICAL", "HIGH", "MEDIUM", "LOW")


@bp.get("/rules")
@permission_required("rule:read")
def rules():
    saved = {r.rule_code: (r.params, r.enabled) for r in db.session.execute(text("SELECT rule_code, params, enabled FROM engine.rule_parameters"))}
    return jsonify(rules=[{"code": c, "title": cls.title, "defaults": cls.default_params,
                           "params": saved.get(c, (None, True))[0], "enabled": saved.get(c, (None, True))[1]}
                          for c, cls in REGISTRY.items()])


@bp.put("/rules/<code>")
@permission_required("rule:configure", step_up=True)
def configure_rule(code):
    if code not in REGISTRY:
        return jsonify(error="Regla inexistente"), 404
    d = request.get_json(silent=True) or {}
    params, enabled = d.get("params", {}), bool(d.get("enabled", True))
    unknown = set(params) - set(REGISTRY[code].default_params)
    if unknown:
        return jsonify(error=f"Parámetros desconocidos: {sorted(unknown)}"), 400
    old = db.session.execute(text("SELECT params, enabled FROM engine.rule_parameters WHERE rule_code=:c"), {"c": code}).first()
    import json
    db.session.execute(text("INSERT INTO engine.rule_parameters (rule_code, params, enabled, updated_by) "
                            "VALUES (:c, CAST(:p AS jsonb), :e, CAST(:u AS uuid)) ON CONFLICT (rule_code) DO UPDATE SET "
                            "params=EXCLUDED.params, enabled=EXCLUDED.enabled, updated_by=EXCLUDED.updated_by, updated_at=now()"),
                       {"c": code, "p": json.dumps(params), "e": enabled, "u": get_jwt_identity()})
    db.session.commit()
    audit("RULE_CONFIGURED", entity_type="rule", entity_id=code, request_id=g.request_id,
          before_data={"params": old.params, "enabled": old.enabled} if old else None, after_data={"params": params, "enabled": enabled})
    return jsonify(status="OK")


@bp.post("/runs")
@permission_required("rule:execute")
def run_rules():
    from app.tasks.audit_tasks import run_anomaly_rules
    job = (request.get_json(silent=True) or {}).get("job_id")
    t = run_anomaly_rules.apply_async(args=[job, get_jwt_identity()], queue="ingestion")
    audit("ENGINE_RUN_REQUESTED", entity_type="engine_run", entity_id=t.id, request_id=g.request_id)
    return jsonify(task_id=t.id), 202


@bp.get("/findings")
@permission_required("finding:read")
def findings():
    status, sev = request.args.get("status", "OPEN").upper(), request.args.get("severity")
    rows = db.session.execute(text(
        "SELECT id, rule_code, severity, entity_type, entity_id, score, message, status, created_at FROM engine.findings "
        "WHERE status=:s AND (CAST(:v AS text) IS NULL OR severity = CAST(:v AS text)) AND rule_code NOT LIKE 'LCFT-%' "
        "ORDER BY array_position(ARRAY['CRITICAL','HIGH','MEDIUM','LOW'], severity), score DESC LIMIT 200"),
        {"s": status, "v": sev.upper() if sev else None}).all()
    return jsonify(findings=[dict(r._mapping) for r in rows])


@bp.get("/findings/summary")
@permission_required("finding:read", "finding:read_summary")
def summary():                                              # agregados: sin datos personales (GERENCIA)
    rows = db.session.execute(text("SELECT severity, status, count(*) n FROM engine.findings GROUP BY 1,2")).all()
    return jsonify(summary=[dict(r._mapping) for r in rows])


def _set_status(fid, new, allowed_from, reason_required=False):
    d = request.get_json(silent=True) or {}
    reason = str(d.get("reason", "")).strip()
    if reason_required and len(reason) < 10:
        return jsonify(error="Indique el motivo (mínimo 10 caracteres)"), 400
    cur = db.session.execute(text("SELECT status FROM engine.findings WHERE id=:i FOR UPDATE"), {"i": fid}).first()
    if cur is None:
        return jsonify(error="No encontrado"), 404
    if cur.status not in allowed_from:
        return jsonify(error=f"Transición no permitida desde {cur.status}"), 409
    db.session.execute(text("UPDATE engine.findings SET status=:s, closed_by=CASE WHEN :c THEN CAST(:u AS uuid) END, "
                            "closed_reason=CASE WHEN :c THEN :r END WHERE id=:i"),
                       {"s": new, "c": new.startswith("CLOSED"), "u": get_jwt_identity(), "r": reason, "i": fid})
    db.session.commit()
    audit("FINDING_" + new, entity_type="finding", entity_id=str(fid), metadata={"reason": reason, "from": cur.status}, request_id=g.request_id)
    return jsonify(status=new)


@bp.post("/findings/<int:fid>/review")
@permission_required("finding:triage")
def review(fid):
    return _set_status(fid, "IN_REVIEW", {"OPEN", "ESCALATED"})


@bp.post("/findings/<int:fid>/escalate")
@permission_required("finding:escalate")
def escalate(fid):
    return _set_status(fid, "ESCALATED", {"OPEN", "IN_REVIEW"}, reason_required=True)


@bp.post("/findings/<int:fid>/close")
@permission_required("finding:close", step_up=True)
def close(fid):
    outcome = "CLOSED_FP" if (request.get_json(silent=True) or {}).get("false_positive") else "CLOSED_RESOLVED"
    return _set_status(fid, outcome, {"OPEN", "IN_REVIEW", "ESCALATED"}, reason_required=True)


@bp.get("/runs")
@permission_required("rule:read")
def list_runs():
    rows = db.session.execute(text(
        "SELECT r.id::text, r.started_at, r.finished_at, r.status, r.job_id::text, "
        "(SELECT count(*) FROM engine.findings f WHERE f.run_id = r.id) AS new_findings "
        "FROM engine.runs r ORDER BY r.started_at DESC LIMIT 20")).all()
    return jsonify(runs=[dict(r._mapping) for r in rows])


@bp.get("/findings/<int:fid>")
@permission_required("finding:read")
def finding_detail(fid):
    r = db.session.execute(text("SELECT id, rule_code, severity, entity_type, entity_id, score, message, evidence, status, "
                                "closed_reason, created_at FROM engine.findings WHERE id=:i"), {"i": fid}).first()
    if r is None:
        return jsonify(error="No encontrado"), 404
    audit("FINDING_VIEWED", entity_type="finding", entity_id=str(fid), request_id=g.request_id)
    return jsonify(finding=dict(r._mapping))
