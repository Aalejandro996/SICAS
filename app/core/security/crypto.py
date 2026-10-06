"""
Cifrado de datos sensibles a nivel de aplicación (AES-256-GCM) con rotación de claves,
e índice ciego (HMAC-SHA256) para buscar/deduplicar sin descifrar (cédula, RIF, secreto MFA).

Formato del texto cifrado:  <key_id>.<base64(nonce(12) || ciphertext || tag)>
La clave activa cifra; cualquier clave del anillo descifra, así se rota sin reencriptar de golpe.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(Exception):
    pass


class KeyRing:
    def __init__(self, keys: dict[str, bytes], active: str):
        if active not in keys:
            raise CryptoError("La clave activa no está en el anillo")
        for kid, k in keys.items():
            if len(k) != 32:
                raise CryptoError(f"La clave {kid} debe tener 32 bytes (AES-256)")
            if "." in kid:
                raise CryptoError("key_id no puede contener '.'")
        self._keys, self.active = keys, active

    @classmethod
    def from_env(cls) -> "KeyRing":
        """SICAS_KEYS='k1:<base64>,k2:<base64>'  SICAS_ACTIVE_KEY='k2'"""
        raw = os.environ.get("SICAS_KEYS")
        if not raw:
            raise CryptoError("SICAS_KEYS no configurada")
        keys = {kid: base64.b64decode(b64) for kid, b64 in (x.split(":", 1) for x in raw.split(","))}
        return cls(keys, os.environ["SICAS_ACTIVE_KEY"])

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> str:
        nonce = os.urandom(12)                                   # único por cifrado
        ct = AESGCM(self._keys[self.active]).encrypt(nonce, plaintext, aad)
        return f"{self.active}." + base64.urlsafe_b64encode(nonce + ct).decode()

    def decrypt(self, token: str, aad: bytes = b"") -> bytes:
        try:
            kid, b64 = token.split(".", 1)
            raw = base64.urlsafe_b64decode(b64.encode())
            return AESGCM(self._keys[kid]).decrypt(raw[:12], raw[12:], aad)
        except Exception as exc:  # noqa: BLE001 - clave desconocida, manipulación o formato
            raise CryptoError("No se pudo descifrar (dato alterado o clave inválida)") from exc

    def needs_rotation(self, token: str) -> bool:
        return token.split(".", 1)[0] != self.active


def normalize_id(value: str) -> str:
    """Cédula/RIF: 'v-12.345.678' -> 'V12345678'."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def blind_index(value: str, key: bytes) -> str:
    """HMAC del identificador normalizado. Permite igualdad/duplicados sin exponer el dato."""
    return hmac.new(key, normalize_id(value).encode(), hashlib.sha256).hexdigest()
