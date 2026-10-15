"""API privada de notificaciones: cada usuario solo ve y atiende sus propios avisos."""
from functools import wraps

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from . import service

bp = Blueprint("notifications", __name__)


def _mfa_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        if not get_jwt().get("mfa"):
            return jsonify(error="MFA requerido"), 403
        return fn(*args, **kwargs)
    return wrapper


@bp.get("/")
@_mfa_required
def list_notifications():
    view = str(request.args.get("view", "all")).lower()
    if view not in {"all", "unread", "pending"}:
        return jsonify(error="Vista de notificaciones no válida."), 400
    return jsonify(notifications=service.list_notifications(str(get_jwt_identity()), view, 100), view=view)


@bp.get("/unread-count")
@_mfa_required
def unread_count():
    return jsonify(count=service.count_unread(str(get_jwt_identity())))


@bp.post("/<uuid:notification_id>/read")
@_mfa_required
def mark_read(notification_id):
    ok = service.mark_read(str(get_jwt_identity()), str(notification_id))
    return (jsonify(status="READ") if ok else jsonify(error="Notificación no encontrada")), (200 if ok else 404)


@bp.post("/<uuid:notification_id>/attend")
@_mfa_required
def mark_attended(notification_id):
    ok = service.mark_attended(str(get_jwt_identity()), str(notification_id))
    return (jsonify(status="ATTENDED") if ok else jsonify(error="Notificación no encontrada")), (200 if ok else 404)
