"""Respaldo de la base de datos con pg_dump (formato personalizado) + huella SHA-256."""
import hashlib
import json
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
    url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
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


# ------------------------------------------------------------------ latido, avisos y verificación de restauración
def _notify_admins(event_key: str, title: str, message: str, target: str = "#/admin-monitor", extra_users=()):
    from app.modules.notifications.service import _insert_for_users, _role_user_ids
    _insert_for_users(sorted(set(_role_user_ids(["SYS_ADMIN"])) | set(extra_users)), category="SYSTEM", event_key=event_key,
                      title=title, message=message, target_path=target, entity_type=None, entity_id=None, actor_user_id=None)
    db.session.commit()


@shared_task
def heartbeat():
    """Lo envía el beat cada minuto y lo ejecuta el worker: si se detiene, el monitor marca el servicio caído."""
    db.session.execute(text("INSERT INTO admin.service_heartbeats (service, last_seen, detail) VALUES ('scheduler', now(), "
                            "jsonb_build_object('host', CAST(:h AS text))) ON CONFLICT (service) DO UPDATE SET last_seen = now(), "
                            "detail = EXCLUDED.detail"), {"h": os.environ.get("HOSTNAME", "")})
    db.session.commit()


@shared_task
def watch_services():
    """Revisa respaldos y cargas y avisa a los administradores una vez por día y por problema."""
    from app.modules.admin.tools import service_status
    st = service_status()
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    for alert_text in st["alerts"]:
        if "worker" in alert_text or "beat" in alert_text:
            continue                                  # si esta tarea corre, el worker y el beat funcionan
        key = hashlib.sha256(alert_text.encode()).hexdigest()[:12]
        _notify_admins(f"system:alert:{today}:{key}", "Alerta del sistema", alert_text)


@shared_task
def warn_certificates():
    """Avisa al titular y a los administradores de los certificados de firma vencidos o por vencer (30 días)."""
    from app.modules.admin.tools import certificate_status
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    status = certificate_status()
    owners = {r["full_name"]: r["id"] for r in db.session.execute(text(
        "SELECT id::text, full_name FROM iam.users WHERE is_active AND removed_at IS NULL")).mappings()}
    for c in status["certificates"]:
        if c.get("state") in ("VENCIDO", "POR_VENCER"):
            msg = (f"El certificado de firma de {c['owner']} ({c.get('subject')}) "
                   + (f"venció hace {-c['days_left']} día(s)." if c["state"] == "VENCIDO" else f"vence en {c['days_left']} día(s)."))
            extra = [owners[c["owner"]]] if c["owner"] in owners else []
            _notify_admins(f"system:cert:{c.get('serial')}:{today}", "Certificado de firma por vencer", msg, "#/admin-monitor", extra)


@shared_task
def verify_restore(request_id: str):
    """Verificación aprobada con doble control: el archivo existe, su SHA-256 coincide y pg_restore puede leerlo completo.

    No sobrescribe la base de producción: la restauración real sigue el procedimiento documentado.
    """
    row = db.session.execute(text("SELECT b.id::text, b.file_path, b.sha256 FROM admin.restore_requests q JOIN admin.backups b "
                                  "ON b.id = q.backup_id WHERE q.id = CAST(:i AS uuid)"), {"i": request_id}).first()
    detail, status = {}, "FAILED"
    try:
        if row is None or not row.file_path or not pathlib.Path(row.file_path).is_file():
            detail["error"] = "El archivo del respaldo ya no está disponible en el servidor"
        else:
            sha = hashlib.sha256()
            with open(row.file_path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(chunk)
            detail["sha256_ok"] = sha.hexdigest() == row.sha256
            exe = shutil.which("pg_restore")
            if not exe:
                detail["error"] = "pg_restore no está disponible en este servidor"
            else:
                out = subprocess.run([exe, "--list", row.file_path], check=True, capture_output=True, timeout=600)
                detail["objects"] = sum(1 for line in out.stdout.decode(errors="replace").splitlines() if line and not line.startswith(";"))
                status = "OK" if detail["sha256_ok"] and detail["objects"] > 0 else "FAILED"
    except Exception as e:  # noqa: BLE001
        detail["error"] = type(e).__name__
    db.session.execute(text("UPDATE admin.restore_requests SET verify_status = :s, verify_detail = CAST(:d AS jsonb), verified_at = now() "
                            "WHERE id = CAST(:i AS uuid)"), {"s": status, "d": json.dumps(detail), "i": request_id})
    db.session.commit()
    audit("RESTORE_VERIFIED", outcome="SUCCESS" if status == "OK" else "FAILURE", entity_type="restore_request",
          entity_id=request_id, metadata=detail)
