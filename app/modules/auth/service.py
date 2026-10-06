"""
Servicio de autenticación (lógica pura, sin Flask): contraseña -> MFA -> sesión.
Principios: respuestas genéricas (no revelar si el usuario existe o está bloqueado), tiempo similar para
usuarios inexistentes, bloqueo progresivo, TOTP sin reutilización, política y historial de contraseñas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

from app.core.security.crypto import KeyRing
from . import lockout, totp
from .lockout import LoginState
from .password import Hasher, validate_password

PASSWORD_HISTORY = 5


class AuthError(Exception):
    """`code` es interno (auditoría). Hacia el cliente siempre se muestra un mensaje genérico."""
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass
class User:
    id: str
    username: str
    email: str
    full_name: str
    password_hash: str
    is_active: bool = True
    state: LoginState = field(default_factory=LoginState)
    must_change_password: bool = False
    roles: list[str] = field(default_factory=list)
    mfa_secret_enc: str | None = None
    mfa_confirmed: bool = False
    mfa_last_step: int | None = None


class UserRepo(Protocol):
    def find_by_username(self, username: str) -> User | None: ...
    def save_state(self, user_id: str, state: LoginState) -> None: ...
    def save_mfa(self, user_id: str, secret_enc: str, confirmed: bool) -> None: ...
    def set_mfa_last_step(self, user_id: str, step: int) -> None: ...
    def set_password(self, user_id: str, password_hash: str) -> None: ...
    def password_history(self, user_id: str, n: int) -> list[str]: ...
    def add_password_history(self, user_id: str, password_hash: str) -> None: ...


Audit = Callable[..., None]


class AuthService:
    def __init__(self, repo: UserRepo, hasher: Hasher, keyring: KeyRing, audit: Audit,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 max_failed: int = 5, lock_minutes: int = 30, totp_window: int = 1):
        self.repo, self.hasher, self.keys, self.audit, self.clock = repo, hasher, keyring, audit, clock
        self.max_failed, self.lock_minutes, self.totp_window = max_failed, lock_minutes, totp_window
        self._dummy = None

    # ---- paso 1: contraseña ----
    def verify_password_step(self, username: str, password: str, ip: str | None = None) -> User:
        now = self.clock()
        user = self.repo.find_by_username(username.strip().lower())
        if user is None:                                     # igualar tiempo con un hash de relleno
            self._dummy = self._dummy or self.hasher.hash("relleno-para-igualar-tiempos")
            self.hasher.verify(self._dummy, password)
            self.audit("LOGIN_FAILED", outcome="FAILURE", metadata={"reason": "UNKNOWN_USER", "ip": ip})
            raise AuthError("INVALID_CREDENTIALS")
        ok = self.hasher.verify(user.password_hash, password)  # siempre se verifica, aun bloqueado
        if lockout.is_locked(user.state, now) or not user.is_active:
            reason = "LOCKED" if user.is_active else "INACTIVE"
            self.audit("LOGIN_REJECTED", outcome="DENIED", entity_type="user", entity_id=user.id, metadata={"reason": reason, "ip": ip})
            raise AuthError(reason)
        if not ok:
            new = lockout.register_failure(user.state, now, self.max_failed, self.lock_minutes)
            self.repo.save_state(user.id, new)
            self.audit("LOGIN_FAILED", outcome="FAILURE", entity_type="user", entity_id=user.id,
                       metadata={"reason": "BAD_PASSWORD", "ip": ip, "locked": new.locked_until is not None})
            raise AuthError("INVALID_CREDENTIALS")
        # La contraseña es correcta; el contador solo se reinicia tras superar también el MFA.
        if self.hasher.needs_rehash(user.password_hash):
            self.repo.set_password(user.id, self.hasher.hash(password))
        return user

    @staticmethod
    def next_step(user: User) -> str:
        if user.must_change_password:
            return "PASSWORD_CHANGE_REQUIRED"
        return "MFA_REQUIRED" if user.mfa_confirmed else "MFA_ENROLL_REQUIRED"

    # ---- paso 2: MFA ----
    def verify_mfa_step(self, user: User, code: str, ip: str | None = None) -> None:
        now = self.clock()
        if lockout.is_locked(user.state, now) or not user.is_active:
            raise AuthError("LOCKED")
        if not user.mfa_confirmed or not user.mfa_secret_enc:
            raise AuthError("MFA_NOT_ENROLLED")
        secret = self.keys.decrypt(user.mfa_secret_enc, aad=user.id.encode()).decode()
        step = totp.verify(secret, code, now=now.timestamp(), window=self.totp_window, last_used_step=user.mfa_last_step)
        if step is None:
            new = lockout.register_failure(user.state, now, self.max_failed, self.lock_minutes)
            self.repo.save_state(user.id, new)
            self.audit("MFA_FAILED", outcome="FAILURE", entity_type="user", entity_id=user.id, metadata={"ip": ip})
            raise AuthError("INVALID_CREDENTIALS")
        self.repo.set_mfa_last_step(user.id, step)
        self.repo.save_state(user.id, lockout.register_success(user.state))
        self.audit("LOGIN_OK", entity_type="user", entity_id=user.id, metadata={"ip": ip})

    # ---- alta de MFA ----
    def begin_mfa_enrollment(self, user: User) -> tuple[str, str]:
        if user.mfa_confirmed:
            raise AuthError("MFA_ALREADY_ENROLLED")
        secret = totp.generate_secret()
        self.repo.save_mfa(user.id, self.keys.encrypt(secret.encode(), aad=user.id.encode()), confirmed=False)
        return secret, totp.provisioning_uri(secret, user.username)

    def confirm_mfa_enrollment(self, user: User, code: str) -> None:
        if user.mfa_confirmed or not user.mfa_secret_enc:
            raise AuthError("MFA_STATE")
        secret = self.keys.decrypt(user.mfa_secret_enc, aad=user.id.encode()).decode()
        step = totp.verify(secret, code, now=self.clock().timestamp(), window=self.totp_window)
        if step is None:
            raise AuthError("INVALID_CREDENTIALS")
        self.repo.save_mfa(user.id, user.mfa_secret_enc, confirmed=True)
        self.repo.set_mfa_last_step(user.id, step)
        self.audit("MFA_ENROLLED", entity_type="user", entity_id=user.id)

    # ---- contraseña ----
    def change_password(self, user: User, old: str, new: str) -> None:
        if not self.hasher.verify(user.password_hash, old):
            self.audit("PASSWORD_CHANGE_FAILED", outcome="FAILURE", entity_type="user", entity_id=user.id)
            raise AuthError("INVALID_CREDENTIALS")
        errs = validate_password(new, username=user.username, email=user.email, full_name=user.full_name)
        if errs:
            raise AuthError("WEAK_PASSWORD", "; ".join(errs))
        for old_hash in [user.password_hash, *self.repo.password_history(user.id, PASSWORD_HISTORY)]:
            if self.hasher.verify(old_hash, new):
                raise AuthError("PASSWORD_REUSED", f"No puede repetir sus últimas {PASSWORD_HISTORY} contraseñas")
        h = self.hasher.hash(new)
        self.repo.add_password_history(user.id, user.password_hash)
        self.repo.set_password(user.id, h)
        self.audit("PASSWORD_CHANGED", entity_type="user", entity_id=user.id)
