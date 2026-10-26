"""Horario laboral, feriados y horas extras.

Horas extras: las solicita el usuario sujeto al horario y las aprueban, en orden, el Jefe de Auditoría
de su dominio (si lo hay), Gerencia y el Contralor, cada uno con MFA reciente. Quien solicita no aprueba.
El Administrador del Sistema ve todas las solicitudes y su uso en su panel.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request
from sqlalchemy import text

from app.core import worktime
from app.core.audit.audit_service import audit
from app.extensions import db

from . import service

bp = Blueprint("schedule", __name__)
STAGES = ("PENDING_JEFE", "PENDING_GERENCIA", "PENDING_CONTRALOR")
STAGE_LABEL = {"PENDING_JEFE": "Jefe de Auditoría", "PENDING_GERENCIA": "Gerencia", "PENDING_CONTRALOR": "Contralor"}
MAX_HOURS, MAX_DAYS_AHEAD = 12, 30


def _err(msg, code=400):
    return jsonify(error=msg), code


def authenticated(fn):
    """JWT válido y MFA completado (cualquier rol)."""
    @wraps(fn)
    def wrapper(*a, **kw):
        verify_jwt_in_request()
        g.claims = get_jwt()
        if not g.claims.get("mfa"):
            return _err("MFA requerido", 403)
        return fn(*a, **kw)
    return wrapper


def _rows(sql, **p):
    return [dict(r._mapping) for r in db.session.execute(text(sql), p).all()]


def _perms():
    """Permisos efectivos (propios y por suplencia) para decidir la etapa que el usuario puede aprobar."""
    from app.modules.engagement.api import perms
    return perms()


def can_approve(stage, row, p=None) -> bool:
    p = p if p is not None else _perms()
    if stage == "PENDING_JEFE":
        from app.modules.engagement.api import holds_stage
        return holds_stage(p, "JEFE", row.get("audit_domain"))
    if stage == "PENDING_GERENCIA":
        return "audit:report_approve_gerente" in p
    if stage == "PENDING_CONTRALOR":
        return "audit:report_approve" in p
    return False


def _parse(value, name):
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{name}: fecha y hora inválidas")
    return (dt.replace(tzinfo=worktime.TZ) if dt.tzinfo is None else dt).astimezone(timezone.utc)


def _notify(user_ids, key, title, message):
    from app.modules.notifications.service import _insert_for_users
    _insert_for_users(user_ids, category="SYSTEM", event_key=key, title=title, message=message, target_path="#/overtime",
                      entity_type="overtime", entity_id=None, actor_user_id=get_jwt_identity())


def _stage_recipients(stage, domain):
    from app.modules.notifications.service import _delegate_ids, _role_user_ids
    if stage == "PENDING_JEFE":
        role = {"SISTEMAS": "JEFE_AUDITORIA_SISTEMAS", "FINANCIERA": "JEFE_AUDITORIA_FINANCIERA"}.get(domain)
        return sorted(set(_role_user_ids([role] if role else [])) | set(_delegate_ids("JEFE", domain)))
    if stage == "PENDING_GERENCIA":
        return sorted(set(_role_user_ids(["GERENCIA"])) | set(_delegate_ids("GERENCIA")))
    return sorted(set(_role_user_ids(["CONTRALOR"])) | set(_delegate_ids("CONTRALOR")))


# ------------------------------------------------------------------ estado y feriados
@bp.get("/status")
@authenticated
def status():
    roles = g.claims.get("roles", [])
    st = worktime.status()
    ot = service.active_overtime(get_jwt_identity())
    upcoming = db.session.execute(text(
        "SELECT starts_at, ends_at FROM admin.overtime_requests WHERE user_id = CAST(:u AS uuid) AND status = 'APPROVED' "
        "AND ends_at > now() ORDER BY starts_at LIMIT 1"), {"u": get_jwt_identity()}).first()
    st.update(exempt=service.exempt(roles),
              overtime={"starts_at": ot["starts_at"], "ends_at": ot["ends_at"]} if ot else None,
              next_overtime={"starts_at": upcoming.starts_at, "ends_at": upcoming.ends_at} if upcoming else None)
    st["blocked"] = not (st["open"] or st["exempt"] or ot)
    if ot and not st["open"]:
        st["minutes_left"] = int((ot["ends_at"] - datetime.now(timezone.utc)).total_seconds() // 60)
        st["closes_at"] = ot["ends_at"].astimezone(worktime.TZ).isoformat()
    return jsonify(st)


@bp.get("/holidays")
@authenticated
def holidays():
    try:
        year = int(request.args.get("year") or worktime.local().year)
    except ValueError:
        return _err("Año inválido")
    if not 2015 <= year <= 2045:
        return _err("Año fuera de rango (2015-2045)")
    rows = _rows("SELECT holiday_date, name, kind, observed FROM admin.holidays WHERE extract(year FROM holiday_date) = :y "
                 "ORDER BY holiday_date", y=year)
    return jsonify(year=year, holidays=rows)


# ------------------------------------------------------------------ horas extras
@bp.post("/overtime")
@authenticated
def request_overtime():
    roles = g.claims.get("roles", [])
    if service.exempt(roles):
        return _err("Su rol no está sujeto al horario laboral: no necesita horas extras", 409)
    d = request.get_json(silent=True) or {}
    try:
        starts, ends = _parse(d.get("starts_at"), "Desde"), _parse(d.get("ends_at"), "Hasta")
    except ValueError as ex:
        return _err(str(ex))
    reason = str(d.get("reason") or "").strip()
    now = datetime.now(timezone.utc)
    if len(reason) < 10:
        return _err("Indique el motivo (mínimo 10 caracteres)")
    if ends <= starts or ends - starts > timedelta(hours=MAX_HOURS):
        return _err(f"El período debe durar entre unos minutos y {MAX_HOURS} horas")
    if ends <= now or starts > now + timedelta(days=MAX_DAYS_AHEAD):
        return _err(f"Solicite horas extras futuras, hasta {MAX_DAYS_AHEAD} días adelante")
    if worktime.business_seconds(starts, ends) >= (ends - starts).total_seconds():
        return _err("Ese período está dentro del horario laboral: no requiere horas extras")
    uid = get_jwt_identity()
    if db.session.execute(text("SELECT 1 FROM admin.overtime_requests WHERE user_id = CAST(:u AS uuid) AND status NOT IN "
                               "('REJECTED','CANCELLED') AND starts_at < :e AND ends_at > :s"), {"u": uid, "s": starts, "e": ends}).first():
        return _err("Ya tiene una solicitud de horas extras que se superpone con ese período", 409)
    domain = service.domain_for(roles)
    first = "PENDING_GERENCIA" if domain == "GENERAL" or any(r in service.JEFE_ROLES for r in roles) else "PENDING_JEFE"
    rid = db.session.execute(text(
        "INSERT INTO admin.overtime_requests (user_id, audit_domain, starts_at, ends_at, reason, status) "
        "VALUES (CAST(:u AS uuid), :d, :s, :e, :r, :st) RETURNING id::text"),
        {"u": uid, "d": domain, "s": starts, "e": ends, "r": reason[:1000], "st": first}).scalar()
    db.session.commit()
    audit("OVERTIME_REQUESTED", entity_type="overtime", entity_id=rid,
          after_data={"starts_at": starts.isoformat(), "ends_at": ends.isoformat(), "reason": reason}, request_id=g.request_id)
    _notify(_stage_recipients(first, domain), f"overtime:{rid}:{first}", "Horas extras por aprobar",
            f"{g.claims.get('username')} solicita horas extras del {starts.astimezone(worktime.TZ):%d/%m %H:%M} al "
            f"{ends.astimezone(worktime.TZ):%d/%m %H:%M}.")
    db.session.commit()
    return jsonify(id=rid, status=first, note=f"Solicitud registrada: pendiente de {STAGE_LABEL[first]}."), 201


OT_SQL = ("SELECT q.id::text, q.user_id::text, u.username, u.full_name, q.audit_domain, q.starts_at, q.ends_at, q.reason, q.status, "
          "q.created_at, j.full_name AS jefe_name, q.jefe_at, ge.full_name AS gerente_name, q.gerente_at, c.full_name AS contralor_name, "
          "q.contralor_at, r.full_name AS rejected_name, q.rejected_at, q.reject_note, q.first_used_at, q.last_used_at "
          "FROM admin.overtime_requests q JOIN iam.users u ON u.id = q.user_id LEFT JOIN iam.users j ON j.id = q.jefe_by "
          "LEFT JOIN iam.users ge ON ge.id = q.gerente_by LEFT JOIN iam.users c ON c.id = q.contralor_by "
          "LEFT JOIN iam.users r ON r.id = q.rejected_by ")


@bp.get("/overtime")
@authenticated
def list_overtime():
    scope = request.args.get("scope", "mine")
    own = set(g.claims.get("perms", []))
    if scope == "mine":
        return jsonify(requests=_rows(OT_SQL + "WHERE q.user_id = CAST(:u AS uuid) ORDER BY q.starts_at DESC LIMIT 100", u=get_jwt_identity()))
    if scope == "pending":
        p = _perms()
        rows = _rows(OT_SQL + "WHERE q.status IN ('PENDING_JEFE','PENDING_GERENCIA','PENDING_CONTRALOR') AND q.ends_at > now() "
                     "AND q.user_id <> CAST(:u AS uuid) ORDER BY q.starts_at", u=get_jwt_identity())
        return jsonify(requests=[r for r in rows if can_approve(r["status"], r, p)])
    if scope == "all":
        if not {"health:read", "user:read", "audit:report_approve"} & own:
            return _err("Sin permiso", 403)
        return jsonify(requests=_rows(OT_SQL + "ORDER BY q.created_at DESC LIMIT 300"))
    return _err("Alcance inválido")


@bp.post("/overtime/<uuid:rid>/decision")
@authenticated
def decide_overtime(rid):
    """Aprobación por etapa (Jefe -> Gerencia -> Contralor), cada una con MFA reciente."""
    from app.core.security.policy import current as current_policy
    import time
    if time.time() - g.claims.get("mfa_at", 0) > current_policy()["step_up_seconds"]:
        return jsonify(error="Reautenticación MFA requerida", step_up_required=True), 401
    row = db.session.execute(text("SELECT id::text, user_id::text, audit_domain, status, starts_at, ends_at FROM admin.overtime_requests "
                                  "WHERE id = CAST(:i AS uuid) FOR UPDATE"), {"i": str(rid)}).first()
    if row is None or row.status not in STAGES:
        return _err("Solicitud inexistente o ya resuelta", 409)
    row = dict(row._mapping)
    if row["user_id"] == get_jwt_identity():
        return _err("Nadie aprueba sus propias horas extras", 403)
    if not can_approve(row["status"], row):
        return _err(f"Esta solicitud está pendiente de {STAGE_LABEL[row['status']]}", 403)
    d = request.get_json(silent=True) or {}
    approve, note, me = bool(d.get("approve")), str(d.get("note") or "").strip()[:500] or None, get_jwt_identity()
    if approve and row["ends_at"] <= datetime.now(timezone.utc):
        approve, note = False, "Vencida: el período terminó sin completar las aprobaciones"
    col = {"PENDING_JEFE": "jefe", "PENDING_GERENCIA": "gerente", "PENDING_CONTRALOR": "contralor"}[row["status"]]
    if approve:
        nxt = {"PENDING_JEFE": "PENDING_GERENCIA", "PENDING_GERENCIA": "PENDING_CONTRALOR", "PENDING_CONTRALOR": "APPROVED"}[row["status"]]
        db.session.execute(text(f"UPDATE admin.overtime_requests SET status = :s, {col}_by = CAST(:u AS uuid), {col}_at = now() "
                                "WHERE id = CAST(:i AS uuid)"), {"s": nxt, "u": me, "i": str(rid)})
    else:
        nxt = "REJECTED"
        db.session.execute(text("UPDATE admin.overtime_requests SET status = 'REJECTED', rejected_by = CAST(:u AS uuid), "
                                "rejected_at = now(), reject_note = :n WHERE id = CAST(:i AS uuid)"), {"u": me, "n": note, "i": str(rid)})
    db.session.commit()
    audit("OVERTIME_" + ("APPROVED" if nxt == "APPROVED" else "STAGE_APPROVED" if approve else "REJECTED"),
          entity_type="overtime", entity_id=str(rid), after_data={"stage": row["status"], "next": nxt, "note": note}, request_id=g.request_id)
    if nxt in STAGES:
        _notify(_stage_recipients(nxt, row["audit_domain"]), f"overtime:{rid}:{nxt}", "Horas extras por aprobar",
                "Hay una solicitud de horas extras pendiente de su aprobación.")
    else:
        _notify([row["user_id"]], f"overtime:{rid}:{nxt}", "Horas extras " + ("aprobadas" if nxt == "APPROVED" else "rechazadas"),
                f"Su solicitud de horas extras del {row['starts_at'].astimezone(worktime.TZ):%d/%m %H:%M} fue "
                + ("aprobada." if nxt == "APPROVED" else f"rechazada{': ' + note if note else '.'}"))
    db.session.commit()
    return jsonify(status=nxt)


@bp.post("/overtime/<uuid:rid>/cancel")
@authenticated
def cancel_overtime(rid):
    n = db.session.execute(text("UPDATE admin.overtime_requests SET status = 'CANCELLED' WHERE id = CAST(:i AS uuid) "
                                "AND user_id = CAST(:u AS uuid) AND status NOT IN ('REJECTED','CANCELLED') AND ends_at > now()"),
                           {"i": str(rid), "u": get_jwt_identity()}).rowcount
    db.session.commit()
    if not n:
        return _err("No se puede cancelar esa solicitud", 409)
    audit("OVERTIME_CANCELLED", entity_type="overtime", entity_id=str(rid), request_id=g.request_id)
    return jsonify(status="CANCELLED")
