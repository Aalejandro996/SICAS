"""Bloqueo de la API fuera del horario laboral para los usuarios sujetos a él."""
from __future__ import annotations

from flask import jsonify, request

ALWAYS_ALLOWED = ("/api/v1/auth/", "/api/v1/health", "/api/v1/schedule/status")


def install(app) -> None:
    @app.before_request
    def _work_schedule():
        if not app.config.get("WORK_SCHEDULE_ENABLED", True) or request.method == "OPTIONS":
            return None
        path = request.path
        if not path.startswith("/api/v1/") or path.startswith(ALWAYS_ALLOWED):
            return None
        from flask_jwt_extended import get_jwt, verify_jwt_in_request
        try:
            verify_jwt_in_request(optional=True)
            claims = get_jwt()
        except Exception:  # noqa: BLE001 - token ausente o inválido: lo resuelve el propio endpoint
            return None
        if not claims or not claims.get("sub") or claims.get("typ") == "challenge":
            return None
        from .service import access_block
        blocked = access_block(claims["sub"], claims.get("roles", []))
        return (jsonify(blocked), 403) if blocked else None
