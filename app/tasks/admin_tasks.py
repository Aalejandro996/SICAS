"""Respaldo de la base de datos con pg_dump (formato personalizado) + huella SHA-256."""
import hashlib
import os
import pathlib
import shutil
import subprocess
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import text

from app.core.audit.audit_service import audit
from app.extensions import db

BACKUP_DIR = pathlib.Path(os.environ.get("SICAS_BACKUP_DIR", pathlib.Path(__file__).resolve().parents[2] / "data" / "backups"))


@shared_task(acks_late=True)
def run_backup(backup_id: str):
    def finish(status, **kw):
        db.session.execute(text("UPDATE admin.backups SET status=:s, finished_at=now(), file_path=:f, size_bytes=:z, sha256=:h, error=:e "
                                "WHERE id=CAST(:i AS uuid)"),
                           {"s": status, "f": kw.get("file"), "z": kw.get("size"), "h": kw.get("sha"), "e": kw.get("error"), "i": backup_id})
        db.session.commit()
        audit("BACKUP_" + status, outcome="SUCCESS" if status == "OK" else "FAILURE", entity_type="backup", entity_id=backup_id,
              metadata={k: v for k, v in kw.items() if k in ("sha", "size", "error")})

    exe = shutil.which("pg_dump")
    if not exe:
        return finish("FAILED", error="pg_dump no está disponible en este equipo (instale el cliente de PostgreSQL)")
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKUP_DIR / f"sicas_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.dump"
    try:
        subprocess.run([exe, "--format=custom", "--no-owner", f"--file={path}", url], check=True, capture_output=True, timeout=3600)
        sha = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                sha.update(chunk)
        finish("OK", file=str(path), size=path.stat().st_size, sha=sha.hexdigest())
    except subprocess.CalledProcessError as e:
        finish("FAILED", error=(e.stderr or b"").decode(errors="replace")[-500:])
    except Exception as e:  # noqa: BLE001
        finish("FAILED", error=type(e).__name__)
