"""Herramientas del Administrador del Sistema.

  - Anulación de auditorías creadas por error (propone el Administrador, aprueba el Contralor).
  - Monitor de los servicios en segundo plano, respaldos y cargas.
  - Vencimiento de certificados de firma y cobertura de firmas escaneadas.
  - Revisión periódica de accesos (con evidencia guardada) y sesiones activas.
  - Verificación de restauración de respaldos con doble control.
  - Prueba del correo saliente.

El Administrador no accede a datos de negocio: de las auditorías solo ve código, unidad y estado.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from flask import current_app, g, jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy import text

from app.core.audit.audit_service import audit
from app.core.security.rbac import permission_required
from app.extensions import db

HEARTBEAT_STALE_SECONDS = 180
CERT_WARNING_DAYS = 30


def _rows(sql, **params):
    return [dict(r._mapping) for r in db.session.execute(text(sql), params).all()]


def _one(sql, **params):
    r = db.session.execute(text(sql), params).first()
    return dict(r._mapping) if r else None


def _err(msg, code=400):
    return jsonify(error=msg), code


def _reason(d, lo=15):
    reason = str(d.get("reason") or "").strip()
    if len(reason) < lo:
        raise ValueError(f"Justifique la solicitud (mínimo {lo} caracteres)")
    return reason[:2000]


# ------------------------------------------------------------------ anulación de auditorías
def annul_audit(audit_id, actor, reason):
    """Anula una auditoría en curso y sin informes. Devuelve el código anterior o lanza ValueError.

    Se conserva (la bitácora la referencia): queda ANULADA, fuera de las listas y con el código liberado.
    """
    a = _one("SELECT id::text, code, status, phase FROM engagement.audits WHERE id = CAST(:a AS uuid) FOR UPDATE", a=audit_id)
    if a is None or a["status"] != "IN_PROGRESS":
        raise ValueError("La auditoría no existe o no está en curso")
    if _one("SELECT 1 AS x FROM engagement.reports WHERE audit_id = CAST(:a AS uuid) LIMIT 1", a=audit_id):
        raise ValueError("La auditoría ya tiene informes generados: no se puede anular")
    who = _one("SELECT username FROM iam.users WHERE id = CAST(:u AS uuid)", u=actor) or {}
    new_code = (a["code"] + "-ANULADA")[:30]
    db.session.execute(text(
        "UPDATE engagement.audits SET status = 'ANULADA', annulled_at = now(), annulled_code = code, code = :nc, "
        "annulled_reason = :r WHERE id = CAST(:a AS uuid)"), {"nc": new_code, "r": reason, "a": audit_id})
    db.session.execute(text(
        "INSERT INTO engagement.change_events (audit_id, entity_type, entity_id, action, changes, reason, audit_phase, "
        "actor_id, actor_username, request_id) VALUES (CAST(:a AS uuid), 'audit', :a, 'AUDIT_ANNULLED', CAST(:c AS jsonb), :r, :ph, "
        "CAST(:u AS uuid), :un, :rid)"),
        {"a": audit_id, "c": json.dumps({"status": {"before": "IN_PROGRESS", "after": "ANULADA"},
                                        "code": {"before": a["code"], "after": new_code}}),
         "r": reason, "ph": a["phase"], "u": actor, "un": who.get("username"), "rid": getattr(g, "request_id", None)})
    return a["code"]


def register_tools(bp):
    @bp.get("/audits/lookup")
    @permission_required("audit:annul_request", "audit:annul_approve")
    def audit_lookup():
        code = str(request.args.get("code") or "").strip().upper()
        if not 5 <= len(code) <= 30:
            return _err("Indique el código de la auditoría (p. ej. S-SC-005-2026-A3)")
        a = _one("SELECT a.id::text, a.code, a.status, a.phase, a.audit_kind, a.created_at, f.code AS file_code, u.name AS unit_name, "
                 "(SELECT count(*) FROM engagement.reports r WHERE r.audit_id = a.id) AS reports "
                 "FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id JOIN engagement.units u ON u.id = f.unit_id "
                 "WHERE a.code = :c", c=code)
        return jsonify(audit=a) if a else _err("No existe una auditoría con ese código", 404)

    @bp.post("/audit-annulments")
    @permission_required("audit:annul_request", step_up=True)
    def request_annulment():
        d = request.get_json(silent=True) or {}
        try:
            reason = _reason(d)
        except ValueError as ex:
            return _err(str(ex))
        a = _one("SELECT a.id::text, a.code, a.status, (SELECT count(*) FROM engagement.reports r WHERE r.audit_id = a.id) AS reports "
                 "FROM engagement.audits a WHERE a.code = :c", c=str(d.get("code") or "").strip().upper())
        if a is None:
            return _err("No existe una auditoría con ese código", 404)
        if a["status"] != "IN_PROGRESS" or a["reports"]:
            return _err("Solo se anulan auditorías en curso y sin informes generados", 409)
        if _one("SELECT 1 AS x FROM engagement.audit_annulment_requests WHERE audit_id = CAST(:a AS uuid) AND status = 'PENDING'", a=a["id"]):
            return _err("Ya hay una solicitud de anulación pendiente para esa auditoría", 409)
        rid = db.session.execute(text(
            "INSERT INTO engagement.audit_annulment_requests (audit_id, audit_code, reason, requested_by) "
            "VALUES (CAST(:a AS uuid), :c, :r, CAST(:u AS uuid)) RETURNING id::text"),
            {"a": a["id"], "c": a["code"], "r": reason, "u": get_jwt_identity()}).scalar()
        db.session.commit()
        audit("AUDIT_ANNULMENT_REQUESTED", entity_type="audit", entity_id=a["id"], after_data={"request": rid, "code": a["code"], "reason": reason},
              request_id=g.request_id)
        return jsonify(id=rid, status="PENDING", note="La anulación queda pendiente de la aprobación del Contralor."), 201

    @bp.get("/audit-annulments")
    @permission_required("audit:annul_request", "audit:annul_approve")
    def list_annulments():
        status = request.args.get("status", "PENDING").upper()
        return jsonify(requests=_rows(
            "SELECT q.id::text, q.audit_code, q.reason, q.status, q.created_at, b.username AS requested_by, d.username AS decided_by, "
            "q.decided_at, q.decision_note FROM engagement.audit_annulment_requests q JOIN iam.users b ON b.id = q.requested_by "
            "LEFT JOIN iam.users d ON d.id = q.decided_by WHERE q.status = :s ORDER BY q.created_at DESC LIMIT 200", s=status))

    @bp.post("/audit-annulments/<uuid:rid>/decision")
    @permission_required("audit:annul_approve", step_up=True)
    def decide_annulment(rid):
        d = request.get_json(silent=True) or {}
        q = _one("SELECT id::text, audit_id::text, audit_code, reason, requested_by::text, status FROM engagement.audit_annulment_requests "
                 "WHERE id = CAST(:i AS uuid) FOR UPDATE", i=str(rid))
        if q is None or q["status"] != "PENDING":
            return _err("Solicitud inexistente o ya resuelta", 409)
        if q["requested_by"] == get_jwt_identity():
            return _err("Doble control: quien solicita la anulación no puede aprobarla", 403)
        approve, note = bool(d.get("approve")), str(d.get("note") or "")[:1000] or None
        try:
            if approve:
                annul_audit(q["audit_id"], get_jwt_identity(), q["reason"])
            db.session.execute(text("UPDATE engagement.audit_annulment_requests SET status = :s, decided_by = CAST(:u AS uuid), "
                                    "decided_at = now(), decision_note = :n WHERE id = CAST(:i AS uuid)"),
                               {"s": "APPROVED" if approve else "REJECTED", "u": get_jwt_identity(), "n": note, "i": str(rid)})
            db.session.commit()
        except ValueError as ex:
            db.session.rollback()
            return _err(str(ex), 409)
        audit("AUDIT_ANNULLED" if approve else "AUDIT_ANNULMENT_REJECTED", entity_type="audit", entity_id=q["audit_id"],
              after_data={"request": str(rid), "code": q["audit_code"], "note": note}, request_id=g.request_id)
        return jsonify(status="APPROVED" if approve else "REJECTED")

    # ------------------------------------------------------------------ monitor
    @bp.get("/monitor")
    @permission_required("health:read")
    def monitor():
        return jsonify(service_status())

    @bp.get("/security-policy")
    @permission_required("param:read", "admin:action_approve")
    def security_policy():
        from app.core.security.policy import FIELDS, current, invalidate
        invalidate()
        return jsonify(policy=current(), limits={k: {"min": lo, "max": hi} for k, (lo, hi, _) in FIELDS.items()})

    # ------------------------------------------------------------------ certificados y firmas
    @bp.get("/certificates")
    @permission_required("health:read")
    def certificates():
        return jsonify(certificate_status())

    # ------------------------------------------------------------------ revisión de accesos
    @bp.get("/access-review")
    @permission_required("user:read")
    def access_review():
        try:
            days = int(request.args.get("inactive_days", 90))
        except ValueError:
            days = 90
        days = min(max(days, 30), 365)
        return jsonify(access_snapshot(days))

    @bp.get("/access-reviews")
    @permission_required("user:read")
    def access_reviews():
        return jsonify(reviews=_rows(
            "SELECT r.id::text, r.performed_at, u.username AS performed_by, r.inactive_days, r.summary->'summary' AS summary, r.note "
            "FROM admin.access_reviews r JOIN iam.users u ON u.id = r.performed_by ORDER BY r.performed_at DESC LIMIT 50"))

    # ------------------------------------------------------------------ sesiones activas
    @bp.get("/sessions")
    @permission_required("session:revoke")
    def sessions():
        return jsonify(sessions=_rows(
            "SELECT u.id::text AS user_id, u.username, u.full_name, count(*) AS sessions, min(t.issued_at) AS since, "
            "max(t.issued_at) AS last_activity, max(t.expires_at) AS expires_at FROM iam.refresh_tokens t "
            "JOIN iam.users u ON u.id = t.user_id WHERE t.revoked_at IS NULL AND t.used_at IS NULL AND t.expires_at > now() "
            "GROUP BY u.id ORDER BY max(t.issued_at) DESC"))

    # ------------------------------------------------------------------ verificación de restauración
    @bp.post("/backups/<uuid:bid>/restore-request")
    @permission_required("backup:restore", step_up=True)
    def request_restore(bid):
        try:
            reason = _reason(request.get_json(silent=True) or {})
        except ValueError as ex:
            return _err(str(ex))
        b = _one("SELECT id::text, status FROM admin.backups WHERE id = CAST(:b AS uuid)", b=str(bid))
        if b is None or b["status"] != "OK":
            return _err("Solo se verifica un respaldo terminado correctamente", 409)
        try:
            rid = db.session.execute(text("INSERT INTO admin.restore_requests (backup_id, reason, requested_by) VALUES "
                                          "(CAST(:b AS uuid), :r, CAST(:u AS uuid)) RETURNING id::text"),
                                     {"b": str(bid), "r": reason, "u": get_jwt_identity()}).scalar()
            db.session.commit()
        except Exception:  # noqa: BLE001 - índice de una sola solicitud pendiente por respaldo
            db.session.rollback()
            return _err("Ya hay una solicitud pendiente para ese respaldo", 409)
        audit("RESTORE_VERIFICATION_REQUESTED", entity_type="backup", entity_id=str(bid), after_data={"request": rid, "reason": reason},
              request_id=g.request_id)
        return jsonify(id=rid, status="PENDING", note="Queda pendiente de la aprobación del Contralor."), 201

    @bp.get("/restore-requests")
    @permission_required("backup:read", "backup:restore_approve")
    def restore_requests():
        return jsonify(requests=_rows(
            "SELECT q.id::text, q.backup_id::text, b.started_at AS backup_at, b.size_bytes, q.reason, q.status, q.created_at, "
            "u.username AS requested_by, d.username AS decided_by, q.decided_at, q.verify_status, q.verify_detail, q.verified_at "
            "FROM admin.restore_requests q JOIN admin.backups b ON b.id = q.backup_id JOIN iam.users u ON u.id = q.requested_by "
            "LEFT JOIN iam.users d ON d.id = q.decided_by ORDER BY q.created_at DESC LIMIT 50"))

    @bp.post("/restore-requests/<uuid:rid>/decision")
    @permission_required("backup:restore_approve", step_up=True)
    def decide_restore(rid):
        d = request.get_json(silent=True) or {}
        q = _one("SELECT id::text, backup_id::text, requested_by::text, status FROM admin.restore_requests WHERE id = CAST(:i AS uuid) FOR UPDATE",
                 i=str(rid))
        if q is None or q["status"] != "PENDING":
            return _err("Solicitud inexistente o ya resuelta", 409)
        if q["requested_by"] == get_jwt_identity():
            return _err("Doble control: quien solicita no puede aprobar", 403)
        approve = bool(d.get("approve"))
        db.session.execute(text("UPDATE admin.restore_requests SET status = :s, decided_by = CAST(:u AS uuid), decided_at = now(), "
                                "decision_note = :n, verify_status = :v WHERE id = CAST(:i AS uuid)"),
                           {"s": "APPROVED" if approve else "REJECTED", "u": get_jwt_identity(), "n": str(d.get("note") or "")[:1000] or None,
                            "v": "RUNNING" if approve else None, "i": str(rid)})
        db.session.commit()
        audit("RESTORE_VERIFICATION_APPROVED" if approve else "RESTORE_VERIFICATION_REJECTED", entity_type="backup",
              entity_id=q["backup_id"], after_data={"request": str(rid)}, request_id=g.request_id)
        if approve:
            from app.tasks.admin_tasks import verify_restore
            verify_restore.apply_async(args=[str(rid)], queue="reports")
        return jsonify(status="APPROVED" if approve else "REJECTED")

    # ------------------------------------------------------------------ acciones con doble verificación
    @bp.post("/actions")
    @permission_required(*sorted({p for p in ACTION_PERMS.values()}), step_up=True)
    def request_action():
        """Primera verificación: MFA reciente del Administrador. La acción queda pendiente del Contralor."""
        d = request.get_json(silent=True) or {}
        action = str(d.get("action") or "").upper()
        if action not in ACTIONS:
            return _err("Acción inválida")
        if ACTION_PERMS[action] not in set(g.claims.get("perms", [])):
            return _err("Sin permiso para solicitar esa acción", 403)
        try:
            reason = _reason(d, lo=10)
            payload, summary = ACTIONS[action]["validate"](d.get("payload") or {})
        except ValueError as ex:
            return _err(str(ex))
        rid = db.session.execute(text(
            "INSERT INTO admin.action_requests (action, payload, summary, reason, requested_by) "
            "VALUES (:a, CAST(:p AS jsonb), :s, :r, CAST(:u AS uuid)) RETURNING id::text"),
            {"a": action, "p": json.dumps(payload), "s": summary, "r": reason, "u": get_jwt_identity()}).scalar()
        db.session.commit()
        audit("ADMIN_ACTION_REQUESTED", entity_type="admin_action", entity_id=rid,
              after_data={"action": action, "payload": payload, "reason": reason}, request_id=g.request_id)
        return jsonify(id=rid, status="PENDING", note="Solicitud registrada: se ejecuta cuando el Contralor la apruebe."), 201

    @bp.get("/actions")
    @permission_required(*sorted({p for p in ACTION_PERMS.values()} | {"admin:action_approve"}))
    def list_actions():
        status = request.args.get("status", "PENDING").upper()
        return jsonify(requests=_rows(
            "SELECT q.id::text, q.action, q.summary, q.payload, q.reason, q.status, q.created_at, u.username AS requested_by, "
            "(q.secret_enc IS NOT NULL) AS has_secret, "
            "d.username AS decided_by, q.decided_at, q.decision_note, q.result FROM admin.action_requests q "
            "JOIN iam.users u ON u.id = q.requested_by LEFT JOIN iam.users d ON d.id = q.decided_by "
            "WHERE (:s = 'ALL' OR q.status = :s) ORDER BY q.created_at DESC LIMIT 100", s=status))

    @bp.post("/actions/<uuid:rid>/decision")
    @permission_required("admin:action_approve", step_up=True)
    def decide_action(rid):
        """Segunda verificación: aprobación del Contralor con MFA reciente; al aprobar se ejecuta la acción."""
        d = request.get_json(silent=True) or {}
        q = _one("SELECT id::text, action, payload, requested_by::text, status FROM admin.action_requests "
                 "WHERE id = CAST(:i AS uuid) FOR UPDATE", i=str(rid))
        if q is None or q["status"] != "PENDING":
            return _err("Solicitud inexistente o ya resuelta", 409)
        if q["requested_by"] == get_jwt_identity():
            return _err("Doble control: quien solicita la acción no puede aprobarla", 403)
        approve, note = bool(d.get("approve")), str(d.get("note") or "")[:1000] or None
        status, result, secret = ("REJECTED", None, None)
        if approve:
            try:
                result = ACTIONS[q["action"]]["execute"](q["payload"], q["requested_by"], get_jwt_identity())
                secret = result.pop("_secret", None) if isinstance(result, dict) else None
                status = "APPROVED"
            except ValueError as ex:
                db.session.rollback()
                status, result = "FAILED", {"error": str(ex)}
        secret_enc = None
        if secret:
            # Solo lo podrá leer, una vez, el Administrador que lo solicitó.
            from app.core.security.crypto import KeyRing
            secret_enc = KeyRing.from_env().encrypt(secret.encode(), aad=f"action:{rid}".encode())
        db.session.execute(text("UPDATE admin.action_requests SET status = :s, decided_by = CAST(:u AS uuid), decided_at = now(), "
                                "decision_note = :n, result = CAST(:r AS jsonb), secret_enc = :se WHERE id = CAST(:i AS uuid)"),
                           {"s": status, "u": get_jwt_identity(), "n": note, "r": json.dumps(result, default=str) if result is not None else None,
                            "se": secret_enc, "i": str(rid)})
        db.session.commit()
        audit("ADMIN_ACTION_" + status, outcome="FAILURE" if status == "FAILED" else "SUCCESS", entity_type="admin_action",
              entity_id=str(rid), after_data={"action": q["action"], "result": result, "note": note}, request_id=g.request_id)
        return jsonify(status=status, result=result)

    @bp.post("/actions/<uuid:rid>/secret")
    @permission_required("user:update", step_up=True)
    def action_secret(rid):
        """Contraseña temporal de un restablecimiento aprobado: solo para quien lo solicitó y una sola vez."""
        from app.core.security.crypto import CryptoError, KeyRing
        q = _one("SELECT requested_by::text, status, secret_enc FROM admin.action_requests WHERE id = CAST(:i AS uuid) FOR UPDATE", i=str(rid))
        if q is None or q["requested_by"] != get_jwt_identity():
            return _err("No encontrada", 404)
        if q["status"] != "APPROVED" or not q["secret_enc"]:
            return _err("La contraseña temporal ya fue consultada o la solicitud no está aprobada", 409)
        try:
            secret = KeyRing.from_env().decrypt(q["secret_enc"], aad=f"action:{rid}".encode()).decode()
        except CryptoError:
            return _err("No se pudo recuperar la contraseña temporal; solicite un nuevo restablecimiento", 500)
        db.session.execute(text("UPDATE admin.action_requests SET secret_enc = NULL, secret_viewed_at = now() WHERE id = CAST(:i AS uuid)"),
                           {"i": str(rid)})
        db.session.commit()
        audit("TEMP_PASSWORD_VIEWED", entity_type="admin_action", entity_id=str(rid), request_id=g.request_id)
        response = jsonify(temporary_password=secret, note="Se muestra una sola vez. Entréguela al usuario por un canal seguro; deberá cambiarla al ingresar.")
        response.headers["Cache-Control"] = "no-store"
        return response


# ------------------------------------------------------------------ acciones del Administrador (validación y ejecución)
def _user_ref(payload):
    uid = str(payload.get("user_id") or "")
    u = _one("SELECT id::text, username, full_name, is_active, removed_at FROM iam.users WHERE id::text = :u", u=uid)
    if u is None or u["removed_at"]:
        raise ValueError("Usuario inexistente o dado de baja")
    return u


def _v_policy(payload):
    from app.core.security.policy import PolicyError, validate
    try:
        value = validate(payload.get("value"))
    except PolicyError as ex:
        raise ValueError(str(ex)) from ex
    return {"value": value}, "Cambiar la política de seguridad: " + ", ".join(f"{k}={v}" for k, v in value.items())


def _x_policy(payload, requester, approver):
    old = db.session.execute(text("SELECT value FROM admin.system_params WHERE key = 'security_policy'")).scalar()
    db.session.execute(text("INSERT INTO admin.system_params (key, value, updated_by) VALUES ('security_policy', CAST(:v AS jsonb), "
                            "CAST(:u AS uuid)) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, "
                            "updated_at = now()"), {"v": json.dumps(payload["value"]), "u": requester})
    from app.core.security.policy import invalidate
    invalidate()
    return {"before": old, "after": payload["value"]}


def _v_revoke(payload):
    u = _user_ref(payload)
    return {"user_id": u["id"]}, f"Cerrar todas las sesiones de {u['full_name']} ({u['username']})"


def _x_revoke(payload, requester, approver):
    n = db.session.execute(text("UPDATE iam.refresh_tokens SET revoked_at = now() WHERE user_id = CAST(:u AS uuid) AND revoked_at IS NULL"),
                           {"u": payload["user_id"]}).rowcount
    return {"revoked": n}


def _v_deactivate(payload):
    u = _user_ref(payload)
    if not u["is_active"]:
        raise ValueError("La cuenta ya está desactivada")
    return {"user_id": u["id"]}, f"Desactivar la cuenta de {u['full_name']} ({u['username']}) por la revisión de accesos"


def _x_deactivate(payload, requester, approver):
    import uuid as _uuid

    from .repositories import SqlAdminRepo
    from .service import AdminError, UserAdminService
    from app.modules.auth.password import Argon2Hasher
    try:
        UserAdminService(SqlAdminRepo(), Argon2Hasher(), audit, lambda: str(_uuid.uuid4())).set_active(requester, payload["user_id"], False)
    except AdminError as ex:
        raise ValueError(ex.message) from ex
    return {"deactivated": payload["user_id"]}


def _v_review(payload):
    days = int(payload.get("inactive_days") or 90)
    if not 30 <= days <= 365:
        raise ValueError("Días sin uso: entre 30 y 365")
    note = str(payload.get("note") or "")[:2000]
    return {"inactive_days": days, "note": note}, f"Registrar la revisión de accesos (sin uso desde {days} días)"


def _x_review(payload, requester, approver):
    snap = access_snapshot(payload["inactive_days"])
    rid = db.session.execute(text("INSERT INTO admin.access_reviews (performed_by, inactive_days, summary, note) "
                                  "VALUES (CAST(:u AS uuid), :d, CAST(:s AS jsonb), :n) RETURNING id::text"),
                             {"u": requester, "d": payload["inactive_days"], "s": json.dumps(snap, default=str),
                              "n": payload.get("note") or None}).scalar()
    return {"review": rid, **snap["summary"]}


def _v_smtp(payload):
    import re
    to = str(payload.get("to") or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to):
        raise ValueError("Correo de destino inválido")
    return {"to": to}, f"Enviar un correo de prueba a {to}"


def _x_smtp(payload, requester, approver):
    import os
    if not os.environ.get("SMTP_HOST"):
        raise ValueError("El correo saliente no está configurado (SMTP_HOST)")
    from app.modules.engagement.api import try_email
    if not try_email(payload["to"], "SICAS: prueba de correo", "Mensaje de prueba enviado desde el panel del Administrador del Sistema.", []):
        raise ValueError("No fue posible enviar el correo; revise la configuración SMTP")
    return {"sent": True}


def _v_reset_password(payload):
    u = _user_ref(payload)
    if not u["is_active"]:
        raise ValueError("La cuenta está desactivada: actívela antes de restablecer la contraseña")
    return {"user_id": u["id"]}, f"Restablecer la contraseña de {u['full_name']} ({u['username']})"


def _x_reset_password(payload, requester, approver):
    from app.modules.auth.password import Argon2Hasher

    from .service import generate_temp_password
    if payload["user_id"] in (requester, approver):
        raise ValueError("Nadie restablece su propia contraseña por esta vía")
    temp = generate_temp_password()
    db.session.execute(text(
        "UPDATE iam.users SET password_hash = :h, password_changed_at = now(), must_change_password = true, failed_attempts = 0, "
        "locked_until = NULL, lockouts = 0 WHERE id = CAST(:u AS uuid) AND is_active AND removed_at IS NULL"),
        {"h": Argon2Hasher().hash(temp), "u": payload["user_id"]})
    db.session.execute(text("UPDATE iam.refresh_tokens SET revoked_at = now() WHERE user_id = CAST(:u AS uuid) AND revoked_at IS NULL"),
                       {"u": payload["user_id"]})
    return {"reset": payload["user_id"], "unlocked": True, "_secret": temp}


def _v_holiday(payload):
    from datetime import date as _date
    try:
        day = _date.fromisoformat(str(payload.get("date") or ""))
    except ValueError:
        raise ValueError("Fecha inválida (AAAA-MM-DD)")
    if not 2015 <= day.year <= 2045:
        raise ValueError("Fecha fuera del calendario (2015-2045)")
    name = str(payload.get("name") or "").strip()
    if not 3 <= len(name) <= 120:
        raise ValueError("Indique el nombre o el decreto (3 a 120 caracteres)")
    observed = bool(payload.get("observed", True))
    verb = "Declarar no laborable" if observed else "Declarar laborable"
    return {"date": day.isoformat(), "name": name, "observed": observed}, f"{verb} el {day:%d/%m/%Y}: {name}"


def _x_holiday(payload, requester, approver):
    db.session.execute(text(
        "INSERT INTO admin.holidays (holiday_date, name, kind, observed, updated_by) VALUES (CAST(:d AS date), :n, 'DECREE', :o, "
        "CAST(:u AS uuid)) ON CONFLICT (holiday_date) DO UPDATE SET observed = EXCLUDED.observed, "
        "name = CASE WHEN admin.holidays.kind = 'DECREE' THEN EXCLUDED.name ELSE admin.holidays.name END, "
        "updated_by = EXCLUDED.updated_by, updated_at = now()"),
        {"d": payload["date"], "n": payload["name"], "o": payload["observed"], "u": requester})
    from app.core import worktime
    worktime.invalidate()
    return {"date": payload["date"], "observed": payload["observed"]}


ACTIONS = {
    "HOLIDAY": {"validate": _v_holiday, "execute": _x_holiday},
    "RESET_PASSWORD": {"validate": _v_reset_password, "execute": _x_reset_password},
    "SECURITY_POLICY": {"validate": _v_policy, "execute": _x_policy},
    "REVOKE_SESSIONS": {"validate": _v_revoke, "execute": _x_revoke},
    "DEACTIVATE_USER": {"validate": _v_deactivate, "execute": _x_deactivate},
    "ACCESS_REVIEW": {"validate": _v_review, "execute": _x_review},
    "SMTP_TEST": {"validate": _v_smtp, "execute": _x_smtp},
}
ACTION_PERMS = {"SECURITY_POLICY": "param:update", "REVOKE_SESSIONS": "session:revoke", "DEACTIVATE_USER": "user:deactivate",
                "ACCESS_REVIEW": "user:update", "SMTP_TEST": "param:update", "RESET_PASSWORD": "user:update",
                "HOLIDAY": "param:update"}


# ------------------------------------------------------------------ consultas compartidas con las tareas
def service_status() -> dict:
    """Estado del worker y del beat, respaldos y cargas."""
    out = {"checked_at": datetime.now(timezone.utc)}
    hb = _one("SELECT last_seen, detail, extract(epoch FROM now() - last_seen)::int AS age FROM admin.service_heartbeats "
              "WHERE service = 'scheduler'")
    out["heartbeat"] = hb
    worker_alive = None
    try:
        celery = current_app.extensions.get("celery")
        if celery is not None and not current_app.config.get("CELERY_EAGER"):
            worker_alive = bool(celery.control.ping(timeout=1.0))
    except Exception:  # noqa: BLE001 - broker no disponible
        worker_alive = False
    beat_ok = hb is not None and hb["age"] <= HEARTBEAT_STALE_SECONDS
    out["worker"] = {"status": "ok" if (worker_alive or beat_ok) else "down",
                     "detail": "responde" if worker_alive else ("procesa tareas programadas" if beat_ok else "no responde")}
    out["beat"] = {"status": "ok" if beat_ok else ("unknown" if hb is None else "down"),
                   "detail": "sin latidos registrados" if hb is None else f"último latido hace {hb['age']} s"}
    out["backups"] = {
        "last_ok": _one("SELECT id::text, started_at, size_bytes FROM admin.backups WHERE status = 'OK' ORDER BY started_at DESC LIMIT 1"),
        "failed_7d": _one("SELECT count(*) AS n FROM admin.backups WHERE status = 'FAILED' AND started_at > now() - interval '7 days'")["n"],
        "last_error": _one("SELECT error, started_at FROM admin.backups WHERE status = 'FAILED' ORDER BY started_at DESC LIMIT 1"),
    }
    out["ingestion"] = {
        "failed_7d": _one("SELECT count(*) AS n FROM insurance.ingestion_jobs WHERE status = 'FAILED' AND created_at > now() - interval '7 days'")["n"],
        "stuck": _one("SELECT count(*) AS n FROM insurance.ingestion_jobs WHERE status IN ('QUEUED','PROCESSING') "
                      "AND created_at < now() - interval '10 minutes'")["n"],
    }
    alerts = []
    if out["worker"]["status"] == "down":
        alerts.append("El worker no responde: no se procesan cargas, respaldos ni alertas.")
    if out["beat"]["status"] == "down":
        alerts.append("El planificador (beat) no envía tareas programadas.")
    if out["backups"]["last_ok"] is None or (datetime.now(timezone.utc) - out["backups"]["last_ok"]["started_at"]).days >= 2:
        alerts.append("No hay un respaldo correcto en las últimas 48 horas.")
    if out["ingestion"]["stuck"]:
        alerts.append(f"Hay {out['ingestion']['stuck']} carga(s) detenida(s) hace más de 10 minutos.")
    out["alerts"] = alerts
    return out


def _institutional_certificates() -> list[dict]:
    from app.modules.reporting.signing import service as signing
    out = []
    for role, label in (("CONTRALOR", "Contralor (institucional)"), ("GERENTE_CI", "Gerencia de Control Interno (institucional)")):
        item = {"kind": "INSTITUCIONAL", "owner": label}
        try:
            item.update(signing.certificate_info(signing.load_signer(current_app.config, role)))
        except Exception as ex:  # noqa: BLE001 - no configurado o ilegible: se informa sin detalles sensibles
            item["error"] = "No configurado o ilegible" if current_app.config.get("ENV") != "dev" else type(ex).__name__
        out.append(item)
    return out


def certificate_status() -> dict:
    now = datetime.now(timezone.utc)
    certs = _institutional_certificates() + [
        {"kind": "PERSONAL", "owner": r["full_name"], "subject": r["subject"], "serial": r["serial"], "not_after": r["not_after"]}
        for r in _rows("SELECT u.full_name, c.subject, c.serial, c.not_after FROM engagement.signing_certificates c "
                       "JOIN iam.users u ON u.id = c.user_id WHERE u.removed_at IS NULL ORDER BY c.not_after")]
    for c in certs:
        if c.get("not_after"):
            c["days_left"] = (c["not_after"] - now).days
            c["state"] = "VENCIDO" if c["days_left"] < 0 else ("POR_VENCER" if c["days_left"] <= CERT_WARNING_DAYS else "VIGENTE")
    signers = _rows(
        "SELECT u.id::text, u.full_name, u.username, array_agg(DISTINCT r.code) AS roles, "
        "EXISTS (SELECT 1 FROM engagement.signature_assets s WHERE s.user_id = u.id AND s.active AND s.signature_type = 'COMPLETA') AS has_signature, "
        "EXISTS (SELECT 1 FROM engagement.signing_certificates c WHERE c.user_id = u.id) AS has_certificate "
        "FROM iam.users u JOIN iam.user_roles ur ON ur.user_id = u.id JOIN iam.roles r ON r.id = ur.role_id "
        "WHERE u.is_active AND u.removed_at IS NULL AND r.code IN ('CONTRALOR','GERENCIA','JEFE_AUDITORIA_FINANCIERA','JEFE_AUDITORIA_SISTEMAS') "
        "GROUP BY u.id ORDER BY u.full_name")
    return {"certificates": certs, "signers": signers, "warning_days": CERT_WARNING_DAYS}


def access_snapshot(inactive_days: int) -> dict:
    users = _rows(
        "SELECT u.id::text, u.username, u.full_name, u.is_active, u.created_at, u.last_login_at, u.locked_until, "
        "COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') AS roles, "
        "EXISTS (SELECT 1 FROM iam.mfa_devices m WHERE m.user_id = u.id AND m.confirmed_at IS NOT NULL) AS mfa, "
        "extract(day FROM now() - COALESCE(u.last_login_at, u.created_at))::int AS idle_days "
        "FROM iam.users u LEFT JOIN iam.user_roles ur ON ur.user_id = u.id LEFT JOIN iam.roles r ON r.id = ur.role_id "
        "WHERE u.removed_at IS NULL GROUP BY u.id ORDER BY u.username")
    from app.core.security.permissions import find_sod_violations
    for u in users:
        flags = []
        if u["is_active"] and u["idle_days"] >= inactive_days:
            flags.append("SIN_USO")
        if u["last_login_at"] is None:
            flags.append("NUNCA_INGRESO")
        if u["is_active"] and not u["mfa"]:
            flags.append("SIN_MFA")
        if not u["roles"] and u["is_active"]:
            flags.append("SIN_ROLES")
        if find_sod_violations(list(u["roles"])):
            flags.append("CONFLICTO_SOD")
        u["flags"] = flags
    summary = {"users": len(users), "active": sum(u["is_active"] for u in users),
               "idle": sum("SIN_USO" in u["flags"] for u in users), "without_mfa": sum("SIN_MFA" in u["flags"] for u in users),
               "sod_conflicts": sum("CONFLICTO_SOD" in u["flags"] for u in users), "inactive_days": inactive_days}
    return {"summary": summary, "users": users}
