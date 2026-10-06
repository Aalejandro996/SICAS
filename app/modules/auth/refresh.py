"""
Rotación de refresh tokens con detección de reutilización (familias de tokens).

Cada inicio de sesión crea una familia. Cada refresh marca el token usado y emite uno nuevo de la
misma familia. Si alguien presenta un token YA usado (robo/replay), se revoca toda la familia.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol


class RefreshError(Exception):
    pass


class ReuseDetected(RefreshError):
    pass


@dataclass(frozen=True)
class RefreshRecord:
    jti: str
    family_id: str
    user_id: str
    expires_at: datetime
    used: bool = False
    revoked: bool = False


class RefreshStore(Protocol):
    def get(self, jti: str) -> RefreshRecord | None: ...
    def save(self, rec: RefreshRecord) -> None: ...
    def mark_used(self, jti: str) -> bool: ...          # atómico: True si estaba sin usar
    def revoke_family(self, family_id: str) -> None: ...
    def revoke_user(self, user_id: str) -> None: ...


class InMemoryRefreshStore:
    def __init__(self):
        self.d: dict[str, RefreshRecord] = {}

    def get(self, jti): return self.d.get(jti)
    def save(self, rec): self.d[rec.jti] = rec

    def mark_used(self, jti):
        r = self.d[jti]
        if r.used:
            return False
        self.d[jti] = replace(r, used=True)
        return True

    def revoke_family(self, family_id):
        for k, r in list(self.d.items()):
            if r.family_id == family_id:
                self.d[k] = replace(r, revoked=True)

    def revoke_user(self, user_id):
        for k, r in list(self.d.items()):
            if r.user_id == user_id:
                self.d[k] = replace(r, revoked=True)


class RefreshService:
    def __init__(self, store: RefreshStore, ttl: timedelta = timedelta(hours=8)):
        self.store, self.ttl = store, ttl

    def start_session(self, user_id: str, now: datetime, jti: str | None = None) -> RefreshRecord:
        rec = RefreshRecord(jti or str(uuid.uuid4()), str(uuid.uuid4()), user_id, now + self.ttl)
        self.store.save(rec)
        return rec

    def rotate(self, jti: str, now: datetime, new_jti: str | None = None) -> RefreshRecord:
        rec = self.store.get(jti)
        if rec is None or rec.revoked or rec.expires_at <= now:
            raise RefreshError("Sesión inválida o expirada")
        if not self.store.mark_used(jti):                       # ya se usó: posible robo
            self.store.revoke_family(rec.family_id)
            raise ReuseDetected("Reutilización de token detectada; sesión revocada")
        new = RefreshRecord(new_jti or str(uuid.uuid4()), rec.family_id, rec.user_id, rec.expires_at)  # no extiende el tope absoluto
        self.store.save(new)
        return new

    def logout(self, jti: str) -> None:
        rec = self.store.get(jti)
        if rec:
            self.store.revoke_family(rec.family_id)
