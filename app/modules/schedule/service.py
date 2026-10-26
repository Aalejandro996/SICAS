"""Acceso según el horario laboral y horas extras (lógica compartida por la API y el inicio de sesión).

Fuera del horario (lunes a viernes de 8:00 a 17:00, hora de Venezuela, sin feriados) solo trabajan el
Administrador del Sistema, Gerencia y el Contralor, y quien tenga horas extras aprobadas en ese momento.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from app.core import worktime
from app.extensions import db

DOMAIN_OF_ROLE = {"AUDITOR_SISTEMAS": "SISTEMAS", "JEFE_AUDITORIA_SISTEMAS": "SISTEMAS",
                  "AUDITOR_FINANCIERO": "FINANCIERA", "JEFE_AUDITORIA_FINANCIERA": "FINANCIERA"}
JEFE_ROLES = ("JEFE_AUDITORIA_SISTEMAS", "JEFE_AUDITORIA_FINANCIERA")


def exempt(roles) -> bool:
    return any(r in worktime.EXEMPT_ROLES for r in (roles or ()))


def domain_for(roles) -> str:
    return next((DOMAIN_OF_ROLE[r] for r in (roles or ()) if r in DOMAIN_OF_ROLE), "GENERAL")


def active_overtime(user_id, now=None) -> dict | None:
    r = db.session.execute(text(
        "SELECT id::text, starts_at, ends_at, last_used_at FROM admin.overtime_requests WHERE user_id = CAST(:u AS uuid) "
        "AND status = 'APPROVED' AND starts_at <= :n AND ends_at > :n ORDER BY ends_at DESC LIMIT 1"),
        {"u": str(user_id), "n": now or datetime.now(timezone.utc)}).first()
    return dict(r._mapping) if r else None


def _mark_used(ot: dict) -> None:
    """Deja constancia del uso de las horas extras (como máximo una escritura cada 5 minutos)."""
    last = ot.get("last_used_at")
    if last and (datetime.now(timezone.utc) - last).total_seconds() < 300:
        return
    db.session.execute(text("UPDATE admin.overtime_requests SET last_used_at = now(), first_used_at = COALESCE(first_used_at, now()) "
                            "WHERE id = CAST(:i AS uuid)"), {"i": ot["id"]})
    db.session.commit()


def access_block(user_id, roles) -> dict | None:
    """None si el usuario puede trabajar ahora; si no, el motivo y la próxima apertura."""
    if exempt(roles) or worktime.is_open():
        return None
    ot = active_overtime(user_id)
    if ot:
        _mark_used(ot)
        return None
    st = worktime.status()
    reason = (f"Hoy es feriado ({st['holiday']})" if st["holiday"] else "Fuera del horario laboral")
    return {"error": f"{reason}. SICAS está disponible de lunes a viernes de 8:00 a 17:00 (hora de Venezuela). "
                     "Para trabajar fuera de ese horario solicite horas extras.",
            "outside_hours": True, "next_open": st["next_open"]}
