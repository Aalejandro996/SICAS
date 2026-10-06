import csv
import io

from celery import shared_task

from app.core.audit.audit_service import audit
from app.modules.ingestion import repositories as repo
from app.modules.ingestion.storage import open_stream
from app.modules.ingestion.reconcile import ControlTotals, reconcile
from app.modules.ingestion.validators import SPECS, normalize_row, validate_row

CHUNK = 5_000


@shared_task(bind=True, autoretry_for=(ConnectionError,), retry_backoff=True, max_retries=3, acks_late=True)
def process_ingestion_job(self, job_id: str):
    job = repo.get_job(job_id)
    repo.set_status(job_id, "PROCESSING")
    spec = SPECS[job.dataset]
    expected = ControlTotals()                       # totales de las filas válidas leídas del archivo
    ok = bad = 0
    try:
        with open_stream(job.object_key) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"))
            missing = [c for c in spec["required"] if c not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"Faltan columnas obligatorias: {', '.join(missing)}")
            batch, rejects = [], []
            for line_no, row in enumerate(reader, start=2):
                errors = validate_row(job.dataset, row)
                if errors:
                    rejects.append({"line": line_no, "errors": errors})
                    continue
                norm = normalize_row(job.dataset, row)
                expected.add(norm, spec["amount_field"])
                batch.append(norm)
                if len(batch) >= CHUNK:
                    repo.bulk_insert_staging(job.dataset, job_id, batch)
                    repo.save_rejects(job_id, rejects)
                    ok += len(batch); bad += len(rejects)
                    repo.update_progress(job_id, ok, bad)
                    batch, rejects = [], []
            repo.bulk_insert_staging(job.dataset, job_id, batch)
            repo.save_rejects(job_id, rejects)
            ok += len(batch); bad += len(rejects)

        loaded_rows, loaded_amounts = repo.promote_staging(job.dataset, job_id)
        diffs = reconcile(expected, loaded_rows, loaded_amounts)
        repo.save_control(job_id, expected, reconciled=not diffs)
        if diffs:                                    # tolerancia cero: la carga queda marcada y se alerta
            repo.set_status(job_id, "FAILED", ok, bad)
            audit(action="INGESTION_RECONCILIATION_FAILED", outcome="FAILURE", entity_type="ingestion_job",
                  entity_id=job_id, metadata={"diferencias": diffs})
            return
        repo.set_status(job_id, "COMPLETED", ok, bad)
        audit(action="INGESTION_COMPLETED", entity_type="ingestion_job", entity_id=job_id,
              after_data={"ok": ok, "rejected": bad, "control_hash": expected.hash_hex})
        from app.tasks.audit_tasks import run_anomaly_rules
        run_anomaly_rules.apply_async(args=[job_id], queue="ingestion")
    except Exception as exc:  # noqa: BLE001
        repo.set_status(job_id, "FAILED", ok, bad)
        audit(action="INGESTION_FAILED", outcome="FAILURE", entity_type="ingestion_job", entity_id=job_id,
              metadata={"error": type(exc).__name__})
        raise
