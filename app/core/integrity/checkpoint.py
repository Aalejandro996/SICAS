"""
Puntos de anclaje firmados del audit trail (Ed25519).
La cadena de hashes detecta alteraciones EN el medio; el anclaje detecta además el BORRADO de las últimas
filas (el último id y su hash quedan firmados y se exportan fuera de la base de datos).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class Checkpoint:
    created_at: datetime
    last_audit_id: int
    last_hash_hex: str
    key_id: str
    signature: bytes

    def message(self) -> bytes:
        return f"SICAS|{self.key_id}|{self.last_audit_id}|{self.last_hash_hex}|{self.created_at.isoformat()}".encode()


def create_checkpoint(priv: Ed25519PrivateKey, key_id: str, last_audit_id: int, last_hash_hex: str,
                      now: datetime) -> Checkpoint:
    cp = Checkpoint(now, last_audit_id, last_hash_hex, key_id, b"")
    return Checkpoint(now, last_audit_id, last_hash_hex, key_id, priv.sign(cp.message()))


def verify_checkpoint(pub: Ed25519PublicKey, cp: Checkpoint) -> bool:
    try:
        pub.verify(cp.signature, cp.message())
        return True
    except InvalidSignature:
        return False


def load_private_key(pem_path: str) -> Ed25519PrivateKey:
    with open(pem_path, "rb") as fh:
        return serialization.load_pem_private_key(fh.read(), password=None)


def load_public_key(pem_path: str) -> Ed25519PublicKey:
    with open(pem_path, "rb") as fh:
        return serialization.load_pem_public_key(fh.read())


def check_against_log(cp: Checkpoint, row_hash_hex_at_id: str | None) -> str | None:
    """Compara el anclaje con la fila actual en la base. Devuelve el problema o None."""
    if row_hash_hex_at_id is None:
        return f"La fila {cp.last_audit_id} anclada ya no existe (posible borrado)"
    if row_hash_hex_at_id != cp.last_hash_hex:
        return f"El hash de la fila {cp.last_audit_id} difiere del anclado (posible alteración)"
    return None
