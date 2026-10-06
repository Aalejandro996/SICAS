"""Escritura del audit trail. El hash encadenado lo calcula el trigger de PostgreSQL."""
from __future__ import annotations

import json
import ipaddress
from typing import Any


def _clean_ip(raw: str | None) -> str | None:
    """Toma la primera IP de la lista y la valida; el campo es INET y un valor inválido haría perder el evento."""
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw.split(",")[0].strip()))
    except ValueError:
        return None


def audit(action: str, outcome: str = "SUCCESS", entity_type: str | None = None,
          entity_id: str | None = None, before_data: Any = None, after_data: Any = None,
          metadata: Any = None, request_id: str | None = None) -> None:
    """Inserta un evento. Nunca debe romper la operación de negocio: si falla, se registra en el log técnico."""
    from flask import has_request_context, request
    from flask_jwt_extended import get_jwt, verify_jwt_in_request
    from sqlalchemy import text

    from app.extensions import db

    actor_id = actor_username = None
    roles: list[str] = []
    ip = ua = None
    if has_request_context():
        ip = _clean_ip(request.headers.get("X-Forwarded-For") or request.remote_addr)
        ua = request.headers.get("User-Agent")
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
            actor_id, actor_username, roles = claims.get("sub"), claims.get("username"), claims.get("roles", [])
        except Exception:  # noqa: BLE001 - sin token válido: evento anónimo (p. ej. login fallido)
            pass

    def dump(v):
        return None if v is None else json.dumps(v, default=str)

    try:
        db.session.execute(
            text("""INSERT INTO audit.audit_log
                    (request_id, actor_id, actor_username, actor_roles, action, entity_type, entity_id,
                     outcome, ip_address, user_agent, before_data, after_data, metadata, row_hash)
                    VALUES (:rid, :aid, :au, :roles, :action, :et, :eid, :outcome, :ip, :ua,
                            CAST(:b AS jsonb), CAST(:a AS jsonb), CAST(:m AS jsonb), '\\x00')"""),
            {"rid": request_id, "aid": actor_id, "au": actor_username, "roles": roles, "action": action,
             "et": entity_type, "eid": entity_id, "outcome": outcome, "ip": ip, "ua": ua,
             "b": dump(before_data), "a": dump(after_data), "m": dump(metadata)},
        )  # row_hash es sobrescrito por el trigger BEFORE INSERT
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        import logging
        logging.getLogger("audit").exception("No se pudo escribir en audit_log (action=%s)", action)
