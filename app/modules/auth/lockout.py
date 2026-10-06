"""Bloqueo por intentos fallidos con duración progresiva. Lógica pura."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta


@dataclass(frozen=True)
class LoginState:
    failed_attempts: int = 0
    locked_until: datetime | None = None
    lockouts: int = 0            # cuántas veces se ha bloqueado (para duración progresiva)


def is_locked(s: LoginState, now: datetime) -> bool:
    return s.locked_until is not None and now < s.locked_until


def register_failure(s: LoginState, now: datetime, max_failed: int = 5, base_minutes: int = 30) -> LoginState:
    attempts = s.failed_attempts + 1
    if attempts < max_failed:
        return replace(s, failed_attempts=attempts)
    minutes = base_minutes * (2 ** min(s.lockouts, 4))       # 30, 60, 120, 240, 480 min
    return LoginState(0, now + timedelta(minutes=minutes), s.lockouts + 1)


def register_success(s: LoginState) -> LoginState:
    return LoginState(0, None, 0)
