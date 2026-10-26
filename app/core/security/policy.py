"""Políticas de seguridad editables por el Administrador del Sistema (parámetro «security_policy»).

Sin parámetro guardado se usan los valores de configuración, que son los vigentes hasta ahora.
Se leen de admin.system_params con una caché corta para no consultar la base en cada petición.
"""
from __future__ import annotations

import time

FIELDS = {
    # clave: (mínimo, máximo, clave de configuración por defecto o valor fijo)
    "max_failed_logins": (3, 10, "MAX_FAILED_LOGINS"),
    "lockout_minutes": (5, 240, "LOCKOUT_MINUTES"),
    "step_up_seconds": (60, 900, "STEP_UP_MAX_AGE_SECONDS"),
    "session_hours": (1, 12, None),
    "password_max_age_days": (0, 365, None),          # 0 = sin vencimiento
}
DEFAULTS = {"max_failed_logins": 5, "lockout_minutes": 30, "step_up_seconds": 300, "session_hours": 8, "password_max_age_days": 0}
_CACHE: dict = {"at": 0.0, "value": None}
TTL_SECONDS = 30


class PolicyError(ValueError):
    pass


def validate(value) -> dict:
    if not isinstance(value, dict) or set(value) - set(FIELDS):
        raise PolicyError("security_policy: objeto con " + ", ".join(FIELDS))
    out = {}
    for key, raw in value.items():
        lo, hi, _ = FIELDS[key]
        if not isinstance(raw, int) or isinstance(raw, bool) or not lo <= raw <= hi:
            raise PolicyError(f"security_policy.{key}: entero entre {lo} y {hi}")
        if key == "password_max_age_days" and 0 < raw < 30:
            raise PolicyError("security_policy.password_max_age_days: 0 (sin vencimiento) o entre 30 y 365")
        out[key] = raw
    return out


def defaults(config) -> dict:
    return {k: (config.get(src) or DEFAULTS[k] if src else DEFAULTS[k]) for k, (_, _, src) in FIELDS.items()}


def current(config=None) -> dict:
    """Política vigente: valores por defecto más los guardados por el Administrador."""
    from flask import current_app

    config = config if config is not None else current_app.config
    now = time.monotonic()
    if _CACHE["value"] is None or now - _CACHE["at"] > TTL_SECONDS:
        saved = {}
        try:
            from sqlalchemy import text

            from app.extensions import db
            saved = db.session.execute(text("SELECT value FROM admin.system_params WHERE key = 'security_policy'")).scalar() or {}
        except Exception:  # noqa: BLE001 - sin base disponible se usan los valores por defecto
            saved = {}
        _CACHE.update(at=now, value=saved)
    merged = defaults(config)
    try:
        merged.update(validate(_CACHE["value"] or {}))
    except PolicyError:
        pass
    return merged


def invalidate() -> None:
    _CACHE.update(at=0.0, value=None)
