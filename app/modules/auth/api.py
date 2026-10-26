"""Endpoints de autenticación: contraseña -> (cambio de clave | alta de MFA | MFA) -> sesión por cookies HttpOnly."""
import base64
import io
import time
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g, jsonify, request
from flask_jwt_extended import (create_access_token, create_refresh_token, decode_token, get_jwt, jwt_required,
                                set_access_cookies, set_refresh_cookies, unset_jwt_cookies, verify_jwt_in_request)

from app.core.audit.audit_service import audit
from app.core.security.crypto import KeyRing
from app.extensions import limiter
from . import service as svc_mod
from .password import Argon2Hasher
from .refresh import RefreshError, RefreshService
from .repositories import SqlRefreshStore, SqlUserRepo, load_permissions
from .service import AuthError, AuthService

bp = Blueprint("auth", __name__)
GENERIC = {"error": "Credenciales inválidas o cuenta no disponible"}


def _service() -> AuthService:
    from app.core.security.policy import current as current_policy
    if "sicas_auth" not in current_app.extensions:
        current_app.extensions["sicas_auth"] = AuthService(SqlUserRepo(), Argon2Hasher(), KeyRing.from_env(), audit)
    svc = current_app.extensions["sicas_auth"]
    pol = current_policy()                                   # política vigente (editable por el Administrador)
    svc.max_failed, svc.lock_minutes = pol["max_failed_logins"], pol["lockout_minutes"]
    return svc


def _refresh() -> RefreshService:
    from app.core.security.policy import current as current_policy
    return RefreshService(SqlRefreshStore(), timedelta(hours=current_policy()["session_hours"]))


def _password_expired(user) -> bool:
    """Vencimiento de contraseña según la política (0 = sin vencimiento)."""
    from sqlalchemy import text

    from app.core.security.policy import current as current_policy
    from app.extensions import db
    days = current_policy()["password_max_age_days"]
    if not days:
        return False
    return bool(db.session.execute(text("SELECT password_changed_at < now() - make_interval(days => :d) FROM iam.users "
                                        "WHERE id = CAST(:u AS uuid)"), {"d": days, "u": user.id}).scalar())


def _challenge(user, step: str) -> str:
    return create_access_token(identity=user.id, additional_claims={"typ": "challenge", "step": step},
                               expires_delta=timedelta(seconds=current_app.config["CHALLENGE_TTL_SECONDS"]))


def _user_from_challenge(allowed: set[str]):
    token = (request.get_json(silent=True) or {}).get("challenge", "")
    try:
        claims = decode_token(token)
    except Exception:  # noqa: BLE001
        raise AuthError("INVALID_CHALLENGE")
    if claims.get("typ") != "challenge" or claims.get("step") not in allowed:
        raise AuthError("INVALID_CHALLENGE")
    user = SqlUserRepo().find_by_id(claims["sub"])
    if user is None or not user.is_active:
        raise AuthError("INVALID_CHALLENGE")
    return user


def _issue_session(user, resp_body: dict | None = None):
    now = datetime.now(timezone.utc)
    perms = load_permissions(user.id)
    mfa_at = int(time.time())
    access = create_access_token(identity=user.id, additional_claims={
        "username": user.username, "roles": user.roles, "perms": perms, "mfa": True, "mfa_at": mfa_at})
    refresh = create_refresh_token(identity=user.id, additional_claims={"mfa_at": mfa_at})
    _refresh().start_session(user.id, now, jti=decode_token(refresh)["jti"])
    resp = jsonify(resp_body or {"status": "OK", "user": {"username": user.username, "full_name": user.full_name,
                                                          "roles": user.roles, "permissions": perms}})
    set_access_cookies(resp, access)
    set_refresh_cookies(resp, refresh)
    return resp


def _fail(e: AuthError):
    return jsonify(GENERIC), 401


@bp.post("/login")
@limiter.limit("10/minute")
@limiter.limit("5/minute", key_func=lambda: (request.get_json(silent=True) or {}).get("username", "").lower())
def login():
    data = request.get_json(silent=True) or {}
    try:
        user = _service().verify_password_step(str(data.get("username", "")), str(data.get("password", "")), request.remote_addr)
    except AuthError as e:
        return _fail(e)
    if current_app.config.get("WORK_SCHEDULE_ENABLED", True):
        from app.modules.schedule.service import access_block
        blocked = access_block(user.id, user.roles)
        if blocked:
            audit("LOGIN_REJECTED", outcome="DENIED", entity_type="user", entity_id=user.id, metadata={"reason": "OUTSIDE_HOURS"})
            return jsonify(blocked), 403
    if not user.must_change_password and _password_expired(user):
        SqlUserRepo().require_password_change(user.id)
        user.must_change_password = True
        audit("PASSWORD_EXPIRED", entity_type="user", entity_id=user.id)
    step = _service().next_step(user)
    return jsonify(status=step, challenge=_challenge(user, step))


@bp.post("/password/change")
@limiter.limit("5/minute")
def change_password():
    data = request.get_json(silent=True) or {}
    try:
        user = _user_from_challenge({"PASSWORD_CHANGE_REQUIRED"})
        _service().change_password(user, str(data.get("old_password", "")), str(data.get("new_password", "")))
    except AuthError as e:
        if e.code in ("WEAK_PASSWORD", "PASSWORD_REUSED"):
            return jsonify(error=e.detail), 400
        return _fail(e)
    user = SqlUserRepo().find_by_id(user.id)
    step = _service().next_step(user)
    return jsonify(status=step, challenge=_challenge(user, step))


def _qr_png_data_uri(uri: str) -> str:
    """Genera un QR PNG localmente; no envía el secreto a terceros."""
    import qrcode

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=7,
        border=4,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/png;base64," + encoded



@bp.post("/mfa/enroll")
@limiter.limit("5/minute")
def mfa_enroll():
    try:
        user = _user_from_challenge({"MFA_ENROLL_REQUIRED"})
        secret, uri = _service().begin_mfa_enrollment(user)
    except AuthError as e:
        return _fail(e)
    qr_data_uri = _qr_png_data_uri(uri)
    response = jsonify(
        secret=secret,
        otpauth_uri=uri,
        qr_data_uri=qr_data_uri,
        challenge=_challenge(user, "MFA_ENROLL_REQUIRED"),
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@bp.post("/mfa/confirm")
@limiter.limit("10/minute")
def mfa_confirm():
    code = str((request.get_json(silent=True) or {}).get("code", ""))
    try:
        user = _user_from_challenge({"MFA_ENROLL_REQUIRED"})
        _service().confirm_mfa_enrollment(user, code)
    except AuthError as e:
        return _fail(e)
    return _issue_session(SqlUserRepo().find_by_id(user.id))


@bp.post("/mfa/verify")
@limiter.limit("10/minute")
def mfa_verify():
    code = str((request.get_json(silent=True) or {}).get("code", ""))
    try:
        user = _user_from_challenge({"MFA_REQUIRED"})
        _service().verify_mfa_step(user, code, request.remote_addr)
    except AuthError as e:
        return _fail(e)
    return _issue_session(user)


@bp.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    claims = get_jwt()
    user = SqlUserRepo().find_by_id(claims["sub"])
    if user is None or not user.is_active:
        resp = jsonify(error="Sesión inválida"); unset_jwt_cookies(resp); return resp, 401
    new_refresh = create_refresh_token(identity=user.id, additional_claims={"mfa_at": claims.get("mfa_at", 0)})
    try:
        _refresh().rotate(claims["jti"], datetime.now(timezone.utc), new_jti=decode_token(new_refresh)["jti"])
    except RefreshError as e:
        audit("TOKEN_REFRESH_REJECTED", outcome="DENIED", entity_type="user", entity_id=user.id, metadata={"reason": type(e).__name__})
        resp = jsonify(error="Sesión inválida"); unset_jwt_cookies(resp); return resp, 401
    perms = load_permissions(user.id)                      # permisos vigentes en cada rotación
    access = create_access_token(identity=user.id, additional_claims={
        "username": user.username, "roles": user.roles, "perms": perms, "mfa": True, "mfa_at": claims.get("mfa_at", 0)})
    resp = jsonify(status="OK")
    set_access_cookies(resp, access); set_refresh_cookies(resp, new_refresh)
    return resp


@bp.post("/logout")
def logout():
    """Revoca la familia de tokens en el servidor y borra las cookies. Cerrar sesión no necesita CSRF."""
    token = request.cookies.get(current_app.config.get("JWT_REFRESH_COOKIE_NAME", "refresh_token_cookie"))
    if token:
        try:
            _refresh().logout(decode_token(token, allow_expired=True)["jti"])
        except Exception:  # noqa: BLE001 - token inválido: igual se limpian las cookies
            pass
    resp = jsonify(status="OK")
    unset_jwt_cookies(resp)
    return resp


@bp.get("/me")
@jwt_required()
def me():
    c = get_jwt()
    if not c.get("mfa"):
        return jsonify(error="No autorizado"), 403
    # La interfaz muestra también las pantallas de las suplencias vigentes; el servidor vuelve a
    # verificar cada permiso delegado en cada acción.
    from app.modules.engagement.api import STAGE_LABEL, active_delegations, delegated_perms
    g.claims = c
    perms = sorted(set(c.get("perms", [])) | delegated_perms())
    acting = [{"stage": STAGE_LABEL.get(d["stage"], d["stage"]), "titular": d["titular_name"], "ends_on": d["ends_on"].isoformat()}
              for d in active_delegations()]
    if "health:read" in c.get("perms", []):
        _warn_if_services_down()
    return jsonify(username=c.get("username"), roles=c.get("roles", []), permissions=perms, delegations=acting)


def _warn_if_services_down():
    """Si el worker o el beat dejaron de latir, avisa a los administradores (una vez por hora).

    Se revisa desde la API porque, con el worker caído, ninguna tarea programada podría avisar.
    """
    from sqlalchemy import text

    from app.extensions import db
    try:
        age = db.session.execute(text("SELECT extract(epoch FROM now() - last_seen) FROM admin.service_heartbeats "
                                      "WHERE service = 'scheduler'")).scalar()
        if age is not None and age > 180:
            from app.tasks.admin_tasks import _notify_admins
            _notify_admins(f"system:down:{datetime.now(timezone.utc):%Y%m%d%H}", "Servicios en segundo plano detenidos",
                           f"El worker o el planificador no registran actividad hace {int(age // 60)} minuto(s): "
                           "no se procesan cargas, respaldos ni alertas.")
    except Exception:  # noqa: BLE001 - el aviso nunca impide el ingreso
        db.session.rollback()


@bp.post("/step-up")
@limiter.limit("10/minute")
@jwt_required()
def step_up():
    """Reautenticación con MFA para acciones críticas (firmar, aprobar roles…). Emite un access token con mfa_at nuevo."""
    c = get_jwt()
    if not c.get("mfa"):
        return jsonify(error="No autorizado"), 403
    code = str((request.get_json(silent=True) or {}).get("code", ""))
    user = SqlUserRepo().find_by_id(c["sub"])
    if user is None or not user.is_active:
        return jsonify(error="No autorizado"), 403
    try:
        _service().verify_mfa_step(user, code, request.remote_addr)
    except AuthError:
        return jsonify(error="Código incorrecto o ya utilizado. Espere al siguiente código."), 401
    perms = load_permissions(user.id)
    access = create_access_token(identity=user.id, additional_claims={
        "username": user.username, "roles": user.roles, "perms": perms, "mfa": True, "mfa_at": int(time.time())})
    resp = jsonify(status="OK")
    set_access_cookies(resp, access)
    return resp
