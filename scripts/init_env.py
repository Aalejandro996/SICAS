"""
Genera el archivo .env de DESARROLLO con secretos aleatorios, la clave AES-256 y el par Ed25519 de anclaje.
Uso:  python scripts/init_env.py          (no sobrescribe un .env existente; use --force)
Las claves se guardan en ./secrets/ (ignorado por git). En producción use Vault/secretos del orquestador.
"""
import base64
import os
import pathlib
import secrets
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = pathlib.Path(__file__).resolve().parents[1]
env_path, sec_dir = ROOT / ".env", ROOT / "secrets"

if env_path.exists() and "--force" not in sys.argv:
    sys.exit(".env ya existe; use --force para regenerarlo (¡invalida claves y sesiones!)")

sec_dir.mkdir(mode=0o700, exist_ok=True)
priv = Ed25519PrivateKey.generate()
(sec_dir / "checkpoint_private.pem").write_bytes(priv.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
(sec_dir / "checkpoint_public.pem").write_bytes(priv.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
os.chmod(sec_dir / "checkpoint_private.pem", 0o600)

lines = [
    "# SOLO DESARROLLO — generado por scripts/init_env.py",
    "SICAS_ENV=dev",
    "SICAS_CELERY_EAGER=1",              # desarrollo: las tareas corren dentro de la petición (no necesita worker)
    "SICAS_COMPANY=Aseguradora (DESARROLLO)",
    f"SECRET_KEY={secrets.token_urlsafe(48)}",
    f"JWT_SECRET_KEY={secrets.token_urlsafe(48)}",
    "DATABASE_URL=postgresql+psycopg://postgres:dev@localhost:5432/contraloria",
    f"SICAS_KEYS=k1:{base64.b64encode(secrets.token_bytes(32)).decode()}",
    "SICAS_ACTIVE_KEY=k1",
    f"SICAS_CHECKPOINT_KEY_PEM={sec_dir / 'checkpoint_private.pem'}",
    f"SICAS_CHECKPOINT_PUB_PEM={sec_dir / 'checkpoint_public.pem'}",
]
env_path.write_text("\n".join(lines) + "\n")
os.chmod(env_path, 0o600)
print(f".env creado en {env_path}\nClaves en {sec_dir}\nGuarde una copia de SICAS_KEYS: sin ella no se puede descifrar el secreto MFA de los usuarios.")
