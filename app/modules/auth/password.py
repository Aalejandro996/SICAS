"""Política de contraseñas y hashing (Argon2id)."""
from __future__ import annotations

import re
from typing import Protocol

MIN_LENGTH = 12
COMMON = {"contraseña123", "password1234", "sicas2026", "aseguradora", "venezuela2026", "123456789012",
          "qwertyuiop12", "administrador"}


class Hasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, hashed: str, password: str) -> bool: ...
    def needs_rehash(self, hashed: str) -> bool: ...


class Argon2Hasher:
    """Argon2id: 64 MiB, 3 iteraciones, 4 hilos (ajustar al hardware para ~250 ms)."""

    def __init__(self):
        from argon2 import PasswordHasher
        self._ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, hashed: str, password: str) -> bool:
        from argon2.exceptions import InvalidHashError, VerificationError
        try:
            return self._ph.verify(hashed, password)
        except (VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hashed: str) -> bool:
        return self._ph.check_needs_rehash(hashed)


def validate_password(password: str, *, username: str = "", email: str = "", full_name: str = "") -> list[str]:
    """Devuelve la lista de incumplimientos (vacía = válida)."""
    errs = []
    if len(password) < MIN_LENGTH:
        errs.append(f"Mínimo {MIN_LENGTH} caracteres")
    if len(password) > 128:
        errs.append("Máximo 128 caracteres")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w\s]"))
    if classes < 3:
        errs.append("Use al menos 3 de: minúsculas, mayúsculas, números, símbolos")
    low = password.lower()
    if low in COMMON:
        errs.append("Contraseña demasiado común")
    for token in {username, email.split("@")[0] if email else "", *full_name.split()}:
        if token and len(token) >= 4 and token.lower() in low:
            errs.append("No debe contener su usuario, correo o nombre")
            break
    if re.search(r"(.)\1{3,}", password):
        errs.append("No use 4 o más caracteres iguales seguidos")
    return errs
