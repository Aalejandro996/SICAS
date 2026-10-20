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
    """Deduplica el hallazgo principal y registra detecciones por ejecución.

    Una reincidencia de un hallazgo cerrado como resuelto lo reabre.
    Un falso positivo conserva su estado terminal para evitar alertas repetitivas.
    """
    inserted = 0

    for f in findings:
        params = {
            "run": run_id,
            "rc": f.rule_code,
            "sev": f.severity.value,
            "et": f.entity_type,
            "eid": f.entity_id,
            "score": f.score,
            "msg": f.message,
            "ev": json.dumps(f.evidence, default=str),
            "fp": f.fingerprint,
        }

        created = session.execute(text(
            "INSERT INTO engine.findings "
            "(run_id, rule_code, severity, entity_type, entity_id, score, message, evidence, fingerprint) "
            "VALUES (CAST(:run AS uuid), :rc, :sev, :et, :eid, :score, :msg, "
            "CAST(:ev AS jsonb), :fp) "
            "ON CONFLICT (fingerprint) DO NOTHING RETURNING id"
        ), params).first()

        if created is not None:
            finding_id = created.id
            inserted += 1
            is_alertable = True
        else:
            existing = session.execute(text(
                "SELECT id, status FROM engine.findings "
                "WHERE fingerprint=:fp FOR UPDATE"
            ), {"fp": f.fingerprint}).first()

            if existing is None:
                raise RuntimeError(
                    "No se pudo recuperar el hallazgo después del conflicto de fingerprint."
                )

            finding_id = existing.id
            reopened = existing.status == "CLOSED_RESOLVED"
            is_alertable = reopened

            session.execute(text(
                "UPDATE engine.findings SET "
                "severity=:sev, score=:score, message=:msg, evidence=CAST(:ev AS jsonb), "
                "status=CASE WHEN status='CLOSED_RESOLVED' THEN 'OPEN' ELSE status END, "
                "closed_by=CASE WHEN status='CLOSED_RESOLVED' THEN NULL ELSE closed_by END, "
                "closed_reason=CASE WHEN status='CLOSED_RESOLVED' THEN NULL ELSE closed_reason END "
                "WHERE id=:id"
            ), {
                "sev": params["sev"],
                "score": params["score"],
                "msg": params["msg"],
                "ev": params["ev"],
                "id": finding_id,
            })

        session.execute(text(
            "INSERT INTO engine.finding_occurrences "
            "(run_id, finding_id, severity, score, message, evidence, is_new) "
            "VALUES (CAST(:run AS uuid), :fid, :sev, :score, :msg, "
            "CAST(:ev AS jsonb), :new) "
            "ON CONFLICT (run_id, finding_id) DO NOTHING"
        ), {
            "run": run_id,
            "fid": finding_id,
            "sev": params["sev"],
            "score": params["score"],
            "msg": params["msg"],
            "ev": params["ev"],
            "new": is_alertable,
        })

    return inserted


def finish_run(session, run_id: str, status: str) -> None:
    session.execute(text("UPDATE engine.runs SET status=:s, finished_at=now() WHERE id=CAST(:id AS uuid)"),
                    {"s": status, "id": run_id})
