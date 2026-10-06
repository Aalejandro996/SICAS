from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy import text

from app.extensions import db

from .validators import SPECS



def exists_by_hash(sha256: str, dataset: str) -> bool:
    return db.session.execute(text("SELECT 1 FROM insurance.ingestion_jobs WHERE sha256=:h AND dataset=:d"),
                              {"h": sha256, "d": dataset}).first() is not None


def create_job(job_id, dataset, sha256, object_key, uploaded_by):
    db.session.execute(text("INSERT INTO insurance.ingestion_jobs (id, dataset, sha256, object_key, uploaded_by) "
                            "VALUES (:id, :d, :h, :k, CAST(:u AS uuid))"),
                       {"id": str(job_id), "d": dataset, "h": sha256, "k": object_key, "u": uploaded_by})
    db.session.commit()


def get_job(job_id):
    r = db.session.execute(text("SELECT * FROM insurance.ingestion_jobs WHERE id=CAST(:id AS uuid)"),
                           {"id": str(job_id)}).first()
    return SimpleNamespace(**r._mapping) if r else None


def set_status(job_id, status, ok=None, bad=None):
    db.session.execute(text("UPDATE insurance.ingestion_jobs SET status=:s, rows_processed=COALESCE(:ok, rows_processed), "
                            "rows_rejected=COALESCE(:bad, rows_rejected), "
                            "finished_at = CASE WHEN :s IN ('COMPLETED','FAILED','CANCELLED') THEN now() END "
                            "WHERE id=CAST(:id AS uuid)"), {"s": status, "ok": ok, "bad": bad, "id": str(job_id)})
    db.session.commit()


def update_progress(job_id, ok, bad):
    set_status(job_id, "PROCESSING", ok, bad)


def save_rejects(job_id, rejects):
    for r in rejects:
        db.session.execute(text("INSERT INTO insurance.ingestion_rejects (job_id, line_no, errors) "
                                "VALUES (CAST(:j AS uuid), :l, CAST(:e AS jsonb))"),
                           {"j": str(job_id), "l": r["line"], "e": json.dumps(r["errors"])})
    db.session.commit()


def bulk_insert_staging(dataset, job_id, rows):
    """Inserta filas YA normalizadas en staging. Los nombres de columna provienen de validators.SPECS
    (lista blanca), nunca del archivo; los valores van como parámetros enlazados."""
    if not rows:
        return
    cols = SPECS[dataset]["cols"]
    stmt = text(f"INSERT INTO staging.{dataset} (job_id, {', '.join(cols)}) "
                f"VALUES (CAST(:job_id AS uuid), {', '.join(':' + c for c in cols)})")
    db.session.execute(stmt, [{**{c: r.get(c) for c in cols}, "job_id": str(job_id)} for r in rows])
    db.session.commit()


_CASTS = {   # columna -> expresión de conversión desde texto de staging (constantes, no entrada del usuario)
    "start_date": "start_date::date", "end_date": "end_date::date", "occurrence_date": "occurrence_date::date",
    "reported_date": "reported_date::date", "period": "period::date", "paid_at": "paid_at::date",
    "sum_insured": "sum_insured::numeric", "premium": "premium::numeric", "claimed_amount": "claimed_amount::numeric",
    "amount": "amount::numeric",
}


def promote_staging(dataset, job_id):
    """staging -> tabla final en UNA transacción; limpia staging; devuelve (filas, montos por moneda) cargados."""
    spec, table = SPECS[dataset], f"insurance.{dataset}"
    cols = spec["cols"]
    select = ", ".join(_CASTS.get(c, c) for c in cols)
    try:
        db.session.execute(text(f"INSERT INTO {table} ({', '.join(cols)}, job_id) "
                                f"SELECT {select}, job_id FROM staging.{dataset} WHERE job_id = CAST(:j AS uuid)"),
                           {"j": str(job_id)})
        db.session.execute(text(f"DELETE FROM staging.{dataset} WHERE job_id = CAST(:j AS uuid)"), {"j": str(job_id)})
        af = spec["amount_field"]
        rows = db.session.execute(text(f"SELECT currency, count(*) n, sum({af}) total FROM {table} "
                                       "WHERE job_id = CAST(:j AS uuid) GROUP BY currency"), {"j": str(job_id)}).all()
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return sum(r.n for r in rows), {r.currency: r.total for r in rows}


def save_control(job_id, totals, reconciled: bool):
    db.session.execute(text("UPDATE insurance.ingestion_jobs SET control_rows=:n, control_amount=:a, control_hash=:h, "
                            "reconciled=:r WHERE id=CAST(:id AS uuid)"),
                       {"n": totals.count, "a": sum(totals.amounts.values()), "h": totals.hash_hex, "r": reconciled,
                        "id": str(job_id)})
    db.session.commit()
