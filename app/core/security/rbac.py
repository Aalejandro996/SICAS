"""Decoradores de autorización. Requieren Flask-JWT-Extended en tiempo de ejecución."""
from __future__ import annotations

import time
from functools import wraps

from flask import current_app, g, jsonify


def _deny(reason: str, code: int = 403):
    from app.core.audit.audit_service import audit

    audit(action="ACCESS_DENIED", outcome="DENIED", metadata={"reason": reason},
          request_id=getattr(g, "request_id", None))
    return jsonify(error=reason), code


def permission_required(*needed: str, require_all: bool = False, step_up: bool = False):
    """
    Exige JWT válido, MFA completado y permiso(s).
      require_all=True  -> el usuario debe tener TODOS los permisos indicados
      step_up=True      -> exige MFA reciente (claim `mfa_at`), p. ej. para firmar
    Los permisos vienen en el claim `perms`, calculado al emitir el token desde iam.role_permissions.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from flask_jwt_extended import get_jwt, verify_jwt_in_request

            verify_jwt_in_request()
            claims = get_jwt()
            if not claims.get("mfa"):
                return _deny("MFA requerido")
            granted = set(claims.get("perms", []))
            ok = set(needed) <= granted if require_all else bool(set(needed) & granted)
            if not ok:
                return _deny("Permiso insuficiente")
            if step_up:
                max_age = current_app.config.get("STEP_UP_MAX_AGE_SECONDS", 300)
                if time.time() - claims.get("mfa_at", 0) > max_age:
                    return jsonify(error="Reautenticación MFA requerida", step_up_required=True), 401
            g.claims = claims
            return fn(*args, **kwargs)
        return wrapper
    return decorator
