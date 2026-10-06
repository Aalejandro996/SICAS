"""Persistencia del motor (PostgreSQL). Se usa desde la tarea Celery."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import text


def load_params(session) -> tuple[dict[str, dict], set[str]]:
    rows = session.execute(text("SELECT rule_code, params, enabled FROM engine.rule_parameters")).all()
    params = {r.rule_code: r.params for r in rows}
    disabled = {r.rule_code for r in rows if not r.enabled}
    return params, disabled


def start_run(session, job_id: str | None, triggered_by: str | None, params_snapshot: dict) -> str:
    run_id = str(uuid.uuid4())
    session.execute(text("INSERT INTO engine.runs (id, job_id, triggered_by, params_snapshot) "
                         "VALUES (:id, CAST(:job AS uuid), CAST(:by AS uuid), CAST(:ps AS jsonb))"),
                    {"id": run_id, "job": job_id, "by": triggered_by, "ps": json.dumps(params_snapshot, default=str)})
    return run_id


def save_findings(session, run_id: str, findings) -> int:
    """Inserta con ON CONFLICT DO NOTHING sobre fingerprint: re-ejecutar no duplica hallazgos."""
    inserted = 0
    for f in findings:
        res = session.execute(text(
            "INSERT INTO engine.findings (run_id, rule_code, severity, entity_type, entity_id, score, message, evidence, fingerprint) "
            "VALUES (CAST(:run AS uuid), :rc, :sev, :et, :eid, :score, :msg, CAST(:ev AS jsonb), :fp) "
            "ON CONFLICT (fingerprint) DO NOTHING"),
            {"run": run_id, "rc": f.rule_code, "sev": f.severity.value, "et": f.entity_type, "eid": f.entity_id,
             "score": f.score, "msg": f.message, "ev": json.dumps(f.evidence, default=str), "fp": f.fingerprint})
        inserted += res.rowcount
    return inserted


def finish_run(session, run_id: str, status: str) -> None:
    session.execute(text("UPDATE engine.runs SET status=:s, finished_at=now() WHERE id=CAST(:id AS uuid)"),
                    {"s": status, "id": run_id})
