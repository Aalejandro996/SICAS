"""TOTP (RFC 6238) sin dependencias externas, con protección contra reutilización del código."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30


def generate_secret(nbytes: int = 20) -> str:
    return base64.b32encode(secrets.token_bytes(nbytes)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6, algo=hashlib.sha1) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), algo).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_at(secret_b32: str, at: float, digits: int = 6, algo=hashlib.sha1) -> str:
    return _hotp(secret_b32, int(at // STEP), digits, algo)


def verify(secret_b32: str, code: str, *, now: float | None = None, window: int = 1,
           last_used_step: int | None = None, digits: int = 6) -> int | None:
    """
    Devuelve el 'step' que coincidió (para guardarlo) o None.
    - window: tolerancia de ±N pasos por desfase de reloj.
    - last_used_step: un código ya usado (o anterior) se rechaza -> evita repetición.
    """
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == digits):
        return None
    now = time.time() if now is None else now
    cur = int(now // STEP)
    matched = None
    for s in range(cur - window, cur + window + 1):          # sin cortocircuito: tiempo casi constante
        if hmac.compare_digest(_hotp(secret_b32, s, digits), code) and matched is None:
            matched = s
    if matched is None or (last_used_step is not None and matched <= last_used_step):
        return None
    return matched


def provisioning_uri(secret_b32: str, username: str, issuer: str = "SICAS") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={secret_b32}&issuer={quote(issuer)}&digits=6&period={STEP}"


def new_backup_codes(n: int = 8) -> list[str]:
    """Códigos de un solo uso (se guardan solo como hash)."""
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper() for _ in range(n)]
