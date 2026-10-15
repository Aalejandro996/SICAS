"""Servicio de notificaciones persistentes y distribución por rol/etapa."""
from __future__ import annotations

from typing import Iterable
import uuid

from sqlalchemy import text
from flask import current_app

from app.extensions import db


def _role_user_ids(role_codes: Iterable[str]) -> list[str]:
    ids: set[str] = set()
    for role_code in set(role_codes):
        rows = db.session.execute(text(
            "SELECT DISTINCT u.id::text AS id FROM iam.users u "
            "JOIN iam.user_roles ur ON ur.user_id=u.id "
            "JOIN iam.roles r ON r.id=ur.role_id "
            "WHERE r.code=:role AND u.is_active IS TRUE"
        ), {"role": role_code}).all()
        ids.update(str(row.id) for row in rows)
    return sorted(ids)


def _report_people(report_id: str, audit_id: str) -> list[str]:
    rows = db.session.execute(text("""
        SELECT DISTINCT users.user_id::text AS id
        FROM (
          SELECT r.created_by AS user_id
          FROM engagement.reports r WHERE r.id=CAST(:report_id AS uuid)
          UNION
          SELECT t.user_id
          FROM engagement.team t
          WHERE t.audit_id=CAST(:audit_id AS uuid)
        ) users
        JOIN iam.users u ON u.id=users.user_id
        WHERE u.is_active IS TRUE
    """), {"report_id": report_id, "audit_id": audit_id}).all()
    return sorted({str(row.id) for row in rows})


def _insert_for_users(
    recipient_ids: Iterable[str], *, category: str, event_key: str,
    title: str, message: str, target_path: str, entity_type: str | None,
    entity_id: str | None, actor_user_id: str | None,
) -> int:
    inserted = 0
    statement = text("""
        INSERT INTO iam.user_notifications
          (id, recipient_user_id, actor_user_id, category, event_key, title,
           message, target_path, entity_type, entity_id)
        SELECT gen_random_uuid(), u.id, CAST(:actor AS uuid), :category, :event_key,
               :title, :message, :target_path, :entity_type, :entity_id
        FROM iam.users u
        WHERE u.id=CAST(:recipient AS uuid) AND u.is_active IS TRUE
        ON CONFLICT (recipient_user_id, event_key) DO NOTHING
    """)
    seen: set[str] = set()
    for recipient_id in recipient_ids:
        recipient_id = str(recipient_id)
        if recipient_id in seen or recipient_id == str(actor_user_id or ""):
            continue
        seen.add(recipient_id)
        result = db.session.execute(statement, {
            "recipient": recipient_id, "actor": actor_user_id, "category": category,
            "event_key": event_key, "title": title, "message": message,
            "target_path": target_path, "entity_type": entity_type, "entity_id": entity_id,
        })
        inserted += max(int(result.rowcount or 0), 0)
    db.session.commit()
    return inserted


def _safe_emit(label: str, callback) -> None:
    """Un fallo de avisos no debe convertir una transición ya confirmada en error."""
    try:
        callback()
    except Exception:  # noqa: BLE001 - se registra; el evento de negocio ya pudo confirmarse
        db.session.rollback()
        current_app.logger.exception("No fue posible emitir notificación SICAS: %s", label)


def _event_key(entity_type: str, entity_id: str, event: str, request_id: str | None) -> str:
    # El ID de petición hace idempotentes las inserciones repetidas durante una petición.
    suffix = str(request_id or uuid.uuid4().hex)
    return f"{entity_type}:{entity_id}:{event}:{suffix}"[:240]


def _audit_path(audit: dict) -> str:
    return f"#/audits/{audit.get('id')}" if audit.get("id") else "#/audits"


def notify_report_submitted(report_id: str, audit: dict, actor_user_id: str,
                            request_id: str | None = None) -> None:
    domain = str(audit.get("audit_domain") or "").upper()
    role = {"FINANCIERA": "JEFE_AUDITORIA_FINANCIERA",
            "SISTEMAS": "JEFE_AUDITORIA_SISTEMAS"}.get(domain)
    if not role:
        return
    def emit():
        recipients = _role_user_ids([role])
        _insert_for_users(recipients, category="REPORT",
            event_key=_event_key("report", report_id, "submitted-to-jefe", request_id),
            title="Informe final recibido para revisión",
            message=f"El informe final de la auditoría {audit.get('code', report_id)} fue enviado y está pendiente de revisión.",
            target_path=_audit_path(audit), entity_type="audit_report", entity_id=report_id,
            actor_user_id=actor_user_id)
    _safe_emit(f"informe enviado {report_id}", emit)


def notify_report_jefe_approved(report_id: str, audit: dict, actor_user_id: str,
                                request_id: str | None = None) -> None:
    def emit():
        recipients = _role_user_ids(["GERENCIA"])
        _insert_for_users(recipients, category="REPORT",
            event_key=_event_key("report", report_id, "received-by-gerencia", request_id),
            title="Informe final recibido por Gerencia",
            message=f"El Jefe de Auditoría aprobó el informe final de {audit.get('code', report_id)}. Está pendiente la revisión y firma de Gerencia.",
            target_path=_audit_path(audit), entity_type="audit_report", entity_id=report_id,
            actor_user_id=actor_user_id)
    _safe_emit(f"aprobación del jefe {report_id}", emit)


def notify_report_returned(report_id: str, audit: dict, stage: str, comment: str,
                           actor_user_id: str, request_id: str | None = None) -> None:
    def emit():
        recipients = _report_people(report_id, str(audit.get("id", "")))
        stage_label = {"IN_REVIEW": "Jefe de Auditoría", "GERENCIA": "Gerencia",
                       "CONTRALOR": "Contraloría"}.get(stage, stage)
        _insert_for_users(recipients, category="REPORT",
            event_key=_event_key("report", report_id, f"returned-{stage}", request_id),
            title="Informe final devuelto para corrección",
            message=f"El informe final de {audit.get('code', report_id)} fue devuelto desde la etapa {stage_label}. Motivo: {comment}",
            target_path=_audit_path(audit), entity_type="audit_report", entity_id=report_id,
            actor_user_id=actor_user_id)
    _safe_emit(f"devolución de informe {report_id}", emit)


def notify_report_signed(report_id: str, audit: dict, role: str, status: str,
                         actor_user_id: str, request_id: str | None = None) -> None:
    domain = str(audit.get("audit_domain") or "").upper()
    head_role = {"FINANCIERA": "JEFE_AUDITORIA_FINANCIERA",
                 "SISTEMAS": "JEFE_AUDITORIA_SISTEMAS"}.get(domain)
    def emit():
        if role == "GERENTE_CI" and status == "CONTRALOR":
            recipients = _role_user_ids(["CONTRALOR"])
            title = "Informe final recibido en Contraloría"
            message = f"Gerencia firmó el informe final de {audit.get('code', report_id)}. Está pendiente la revisión/firma de Contraloría."
            event = "received-by-contralor"
        elif role == "CONTRALOR" and status == "SIGNED":
            recipients = _report_people(report_id, str(audit.get("id", "")))
            recipients = sorted(set(recipients) | set(_role_user_ids(["GERENCIA"] + ([head_role] if head_role else []))) )
            title = "Informe final aprobado y firmado"
            message = f"Contraloría completó la aprobación y firma del informe final de {audit.get('code', report_id)}. El documento está disponible en SICAS."
            event = "final-signed"
        else:
            return
        _insert_for_users(recipients, category="REPORT",
            event_key=_event_key("report", report_id, event, request_id),
            title=title, message=message, target_path=_audit_path(audit),
            entity_type="audit_report", entity_id=report_id, actor_user_id=actor_user_id)
    _safe_emit(f"firma de informe {report_id}", emit)


def _role_request_row(request_id: str):
    return db.session.execute(text("""
        SELECT q.id::text AS id, q.target_user_id::text AS target_user_id,
               q.requested_by::text AS requested_by, q.action, q.reason,
               q.status, q.decision_note, ro.code AS role,
               u.username AS target_username
        FROM iam.role_change_requests q
        JOIN iam.roles ro ON ro.id=q.role_id
        JOIN iam.users u ON u.id=q.target_user_id
        WHERE q.id=CAST(:id AS uuid)
    """), {"id": request_id}).mappings().first()


def notify_role_request_created(request_id: str, actor_user_id: str,
                                request_id_trace: str | None = None) -> None:
    def emit():
        row = _role_request_row(request_id)
        if not row:
            return
        recipients = _role_user_ids(["CONTRALOR"])
        message = (f"Solicitud {row['action']} del rol {row['role']} para {row['target_username']}. "
                   f"Motivo: {row['reason']}")
        _insert_for_users(recipients, category="ROLE",
            event_key=_event_key("role_request", request_id, "pending", request_id_trace),
            title="Nueva solicitud de cambio de rol", message=message,
            target_path="#/roles", entity_type="role_request", entity_id=request_id,
            actor_user_id=actor_user_id)
    _safe_emit(f"solicitud de rol {request_id}", emit)


def notify_role_request_decision(request_id: str, status: str, actor_user_id: str,
                                 request_id_trace: str | None = None) -> None:
    def emit():
        row = _role_request_row(request_id)
        if not row:
            return
        recipients = {str(row["requested_by"]), str(row["target_user_id"])}
        outcome = "aprobada" if status == "APPROVED" else "rechazada"
        message = (f"La solicitud {row['action']} del rol {row['role']} para {row['target_username']} "
                   f"fue {outcome}." + (f" Nota: {row['decision_note']}" if row["decision_note"] else ""))
        _insert_for_users(recipients, category="ROLE",
            event_key=_event_key("role_request", request_id, f"decision-{status.lower()}", request_id_trace),
            title=f"Solicitud de cambio de rol {outcome}", message=message,
            target_path="#/notifications", entity_type="role_request", entity_id=request_id,
            actor_user_id=actor_user_id)
    _safe_emit(f"decisión de solicitud de rol {request_id}", emit)


def list_notifications(user_id: str, view: str = "all", limit: int = 100) -> list[dict]:
    predicates = {
        "all": "TRUE",
        "unread": "read_at IS NULL",
        "pending": "attended_at IS NULL",
    }
    if view not in predicates:
        raise ValueError("Filtro de notificaciones no válido.")
    safe_limit = max(1, min(int(limit), 100))
    rows = db.session.execute(text(f"""
        SELECT id::text AS id, category, title, message, target_path,
               entity_type, entity_id, created_at, read_at, attended_at
        FROM iam.user_notifications
        WHERE recipient_user_id=CAST(:user_id AS uuid) AND {predicates[view]}
        ORDER BY created_at DESC, id DESC
        LIMIT :limit
    """), {"user_id": user_id, "limit": safe_limit}).mappings().all()
    return [dict(row) for row in rows]


def count_unread(user_id: str) -> int:
    return int(db.session.execute(text("""
        SELECT count(*) FROM iam.user_notifications
        WHERE recipient_user_id=CAST(:user_id AS uuid) AND read_at IS NULL
    """), {"user_id": user_id}).scalar_one())


def mark_read(user_id: str, notification_id: str) -> bool:
    row = db.session.execute(text("""
        UPDATE iam.user_notifications SET read_at=COALESCE(read_at, now())
        WHERE id=CAST(:id AS uuid) AND recipient_user_id=CAST(:user_id AS uuid)
        RETURNING id
    """), {"id": notification_id, "user_id": user_id}).first()
    db.session.commit()
    return row is not None


def mark_attended(user_id: str, notification_id: str) -> bool:
    row = db.session.execute(text("""
        UPDATE iam.user_notifications
        SET read_at=COALESCE(read_at, now()), attended_at=COALESCE(attended_at, now())
        WHERE id=CAST(:id AS uuid) AND recipient_user_id=CAST(:user_id AS uuid)
        RETURNING id
    """), {"id": notification_id, "user_id": user_id}).first()
    db.session.commit()
    return row is not None
