"""Parámetros del sistema editables desde la aplicación. Lista blanca con validación estricta (nada de claves libres)."""
from __future__ import annotations

import re

EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
RULE_CODES = {"DUP-CLAIM", "DUP-POLICY", "EARLY-CLAIM", "RESERVE-RANGE", "BENFORD-1D",
              "LCFT-THRESHOLD", "LCFT-STRUCTURING", "LCFT-WATCHLIST"}


class ParamError(ValueError):
    pass


def _company(v):
    if not isinstance(v, str) or not 3 <= len(v.strip()) <= 120:
        raise ParamError("company_name: texto de 3 a 120 caracteres")
    return v.strip()


def _int_range(lo, hi, name):
    def f(v):
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ParamError(f"{name}: entero entre {lo} y {hi}")
        return v
    return f


def _thresholds(v):
    if not isinstance(v, dict) or set(v) != {"satisfactorio", "mejora"}:
        raise ParamError("rating_thresholds: {satisfactorio, mejora}")
    s, m = v["satisfactorio"], v["mejora"]
    if any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in (s, m)) or not 1 <= m < s <= 100:
        raise ParamError("rating_thresholds: números con 1 <= mejora < satisfactorio <= 100")
    return {"satisfactorio": s, "mejora": m}


def _routing(v):
    if not isinstance(v, dict):
        raise ParamError("alert_routing: objeto {regla: correo}")
    out = {}
    for rule, email in v.items():
        if rule not in RULE_CODES:
            raise ParamError(f"alert_routing: regla desconocida {rule}")
        if not isinstance(email, str) or not EMAIL_RX.match(email.strip()):
            raise ParamError(f"alert_routing: correo inválido para {rule}")
        out[rule] = email.strip().lower()
    return out


def _security_policy(v):
    from app.core.security.policy import PolicyError, validate
    try:
        return validate(v)
    except PolicyError as e:
        raise ParamError(str(e)) from e


SPECS = {
    "company_name": (_company, "Aseguradora"),
    "retention_years": (_int_range(1, 30, "retention_years"), 10),
    "findings_sla_days": (_int_range(1, 90, "findings_sla_days"), 15),
    "alert_routing": (_routing, {}),
    "rating_thresholds": (_thresholds, {"satisfactorio": 70, "mejora": 50}),
    # Vacío = valores vigentes de configuración (5 intentos, 30 min de bloqueo, MFA reciente de 5 min, sesión de 8 h).
    "security_policy": (_security_policy, {}),
}


def validate_param(key: str, value):
    if key not in SPECS:
        raise ParamError(f"Parámetro desconocido: {key}")
    return SPECS[key][0](value)


def defaults() -> dict:
    return {k: d for k, (_, d) in SPECS.items()}
