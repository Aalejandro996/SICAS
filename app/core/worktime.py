"""Horario laboral de SICAS: lunes a viernes de 8:00 a 17:00, hora de Venezuela, sin feriados.

Feriados nacionales:
  - Fijos: 1 ene, 19 abr, 1 may, 24 jun, 5 jul, 24 jul, 12 oct, 24, 25 y 31 dic.
  - Móviles (se calculan cada año desde el Domingo de Pascua): lunes y martes de Carnaval,
    Jueves y Viernes Santo.
  - Decretados por el Ejecutivo: tabla admin.holidays (kind = 'DECREE'), con doble verificación.
    La misma tabla permite marcar un feriado calculado como no observado (observed = false).

La misma regla existe en SQL (engagement.business_seconds) para los promedios del tablero.
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Caracas")
OPEN, CLOSE = time(8, 0), time(17, 0)
DAY_SECONDS = 9 * 3600                     # un día hábil = 9 horas
WARNING_MINUTES = 15
EXEMPT_ROLES = ("SYS_ADMIN", "GERENCIA", "CONTRALOR")

FIXED = {(1, 1): "Año Nuevo", (4, 19): "Declaración de la Independencia", (5, 1): "Día del Trabajador",
         (6, 24): "Batalla de Carabobo", (7, 5): "Día de la Independencia", (7, 24): "Natalicio del Libertador",
         (10, 12): "Día de la Resistencia Indígena", (12, 24): "Víspera de Navidad", (12, 25): "Navidad",
         (12, 31): "Fin de año"}


def easter(year: int) -> date:
    """Domingo de Pascua (algoritmo gregoriano anónimo)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lday = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lday) // 451
    month = (h + lday - 7 * m + 114) // 31
    day = (h + lday - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def computed_holidays(year: int) -> dict[date, str]:
    out = {date(year, m, d): name for (m, d), name in FIXED.items()}
    e = easter(year)
    out.update({e - timedelta(days=48): "Lunes de Carnaval", e - timedelta(days=47): "Martes de Carnaval",
                e - timedelta(days=3): "Jueves Santo", e - timedelta(days=2): "Viernes Santo"})
    return out


_CACHE: dict = {"at": 0.0, "rows": None}


def _overrides() -> list[dict]:
    """Feriados decretados y feriados calculados no observados (de la base; vacío si no hay base)."""
    if _CACHE["rows"] is None or _time.monotonic() - _CACHE["at"] > 300:
        rows = []
        try:
            from sqlalchemy import text

            from app.extensions import db
            rows = [dict(r._mapping) for r in db.session.execute(text(
                "SELECT holiday_date, name, kind, observed FROM admin.holidays WHERE kind = 'DECREE' OR NOT observed"))]
        except Exception:  # noqa: BLE001
            try:
                from app.extensions import db
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
        _CACHE.update(at=_time.monotonic(), rows=rows)
    return _CACHE["rows"]


def invalidate() -> None:
    _CACHE.update(at=0.0, rows=None)


def holidays(year: int, overrides: list[dict] | None = None) -> dict[date, str]:
    out = computed_holidays(year)
    for r in (overrides if overrides is not None else _overrides()):
        d = r["holiday_date"]
        if d.year != year:
            continue
        if r.get("observed", True):
            out[d] = r["name"]
        else:
            out.pop(d, None)
    return out


def is_workday(d: date, overrides: list[dict] | None = None) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year, overrides)


def local(dt: datetime | None = None) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def is_open(dt: datetime | None = None, overrides: list[dict] | None = None) -> bool:
    t = local(dt)
    return is_workday(t.date(), overrides) and OPEN <= t.time() < CLOSE


def closes_at(dt: datetime | None = None, overrides: list[dict] | None = None) -> datetime | None:
    t = local(dt)
    return datetime.combine(t.date(), CLOSE, TZ) if is_open(t, overrides) else None


def next_open(dt: datetime | None = None, overrides: list[dict] | None = None) -> datetime:
    t = local(dt)
    if is_open(t, overrides):
        return t
    d = t.date() if t.time() < OPEN else t.date() + timedelta(days=1)
    while not is_workday(d, overrides):
        d += timedelta(days=1)
    return datetime.combine(d, OPEN, TZ)


def business_seconds(start: datetime, end: datetime, overrides: list[dict] | None = None) -> int:
    """Segundos hábiles entre dos instantes (solo lunes a viernes de 8:00 a 17:00, sin feriados)."""
    if start is None or end is None or end <= start:
        return 0
    s, e = local(start), local(end)
    total, d = 0, s.date()
    while d <= e.date():
        if is_workday(d, overrides):
            lo = max(s, datetime.combine(d, OPEN, TZ))
            hi = min(e, datetime.combine(d, CLOSE, TZ))
            if hi > lo:
                total += int((hi - lo).total_seconds())
        d += timedelta(days=1)
    return total


def status(dt: datetime | None = None) -> dict:
    """Estado del horario para la interfaz: abierto, cierre, minutos restantes y próxima apertura."""
    t = local(dt)
    hol = holidays(t.year).get(t.date())
    open_ = is_open(t)
    close = closes_at(t)
    return {"open": open_, "now": t.isoformat(), "holiday": hol, "closes_at": close.isoformat() if close else None,
            "minutes_left": int((close - t).total_seconds() // 60) if close else 0,
            "next_open": next_open(t).isoformat(), "warning_minutes": WARNING_MINUTES,
            "schedule": "Lunes a viernes de 8:00 a 17:00 (hora de Venezuela), excepto feriados"}
