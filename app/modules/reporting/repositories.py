from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from app.extensions import db

from .workflow import ReportState


def get_report(report_id) -> ReportState | None:
    r = db.session.execute(text("SELECT id, status, drafted_by, approved_by, body, approved_body_sha256 "
                                "FROM reporting.reports WHERE id=CAST(:id AS uuid)"), {"id": str(report_id)}).first()
    if not r:
        return None
    return ReportState(str(r.id), r.status, str(r.drafted_by), str(r.approved_by) if r.approved_by else None,
                       r.body, r.approved_body_sha256)


def mark_submitted(report_id):
    db.session.execute(text("UPDATE reporting.reports SET status='SUBMITTED', submitted_at=now() WHERE id=CAST(:id AS uuid)"),
                       {"id": str(report_id)})
    db.session.commit()


def mark_approved(report_id, approver, body_sha):
    db.session.execute(text("UPDATE reporting.reports SET status='APPROVED', approved_by=CAST(:u AS uuid), "
                            "approved_at=now(), approved_body_sha256=:h WHERE id=CAST(:id AS uuid)"),
                       {"id": str(report_id), "u": approver, "h": body_sha})
    db.session.commit()


def mark_returned(report_id, reason):
    db.session.execute(text("UPDATE reporting.reports SET status='RETURNED', return_reason=:r WHERE id=CAST(:id AS uuid)"),
                       {"id": str(report_id), "r": reason})
    db.session.commit()


def register_signed(report_id, signer_user_id, signed, object_key, version=1) -> str:
    doc_id = str(uuid.uuid4())
    db.session.execute(text(
        "INSERT INTO reporting.signed_documents (id, report_id, version, sha256_unsigned, sha256_signed, object_key, "
        "signer_user_id, signer_subject, cert_serial, cert_sha256, signed_at, tsa_url, timestamp_embedded) "
        "VALUES (CAST(:id AS uuid), CAST(:r AS uuid), :v, :hu, :hs, :k, CAST(:u AS uuid), :sub, :ser, :cs, :at, :tsa, :ts)"),
        {"id": doc_id, "r": str(report_id), "v": version, "hu": signed.sha256_unsigned, "hs": signed.sha256_signed,
         "k": object_key, "u": signer_user_id, "sub": signed.signer_subject, "ser": signed.cert_serial,
         "cs": signed.cert_sha256, "at": signed.signed_at, "tsa": signed.tsa_url, "ts": signed.timestamp_embedded})
    db.session.execute(text("UPDATE reporting.reports SET status='SIGNED' WHERE id=CAST(:id AS uuid)"), {"id": str(report_id)})
    db.session.commit()
    return doc_id


def find_signed_by_hash(sha256_signed: str):
    return db.session.execute(text("SELECT report_id, version, signer_subject, signed_at FROM reporting.signed_documents "
                                   "WHERE sha256_signed=:h"), {"h": sha256_signed}).first()


# ------------------------------------------------------------------ redacción y consulta
def next_folio_number() -> int:
    return db.session.execute(text("SELECT nextval('reporting.folio_seq')")).scalar_one()


def create_report(report_id, folio, kind, title, body, drafted_by):
    db.session.execute(text("INSERT INTO reporting.reports (id, folio, kind, title, body, drafted_by) "
                            "VALUES (CAST(:i AS uuid), :f, :k, :t, CAST(:b AS jsonb), CAST(:u AS uuid))"),
                       {"i": str(report_id), "f": folio, "k": kind, "t": title, "b": json.dumps(body), "u": drafted_by})
    db.session.commit()


def update_draft(report_id, title, body):
    db.session.execute(text("UPDATE reporting.reports SET title=:t, body=CAST(:b AS jsonb), updated_at=now() WHERE id=CAST(:i AS uuid)"),
                       {"t": title, "b": json.dumps(body), "i": str(report_id)})
    db.session.commit()


def fetch_findings(ids):
    if not ids:
        return []
    rows = db.session.execute(text("SELECT id, rule_code, severity, entity_id, message FROM engine.findings "
                                   "WHERE id = ANY(CAST(:ids AS bigint[])) ORDER BY id"), {"ids": list(ids)}).all()
    return [dict(r._mapping) for r in rows]


def list_reports(statuses):
    rows = db.session.execute(text(
        "SELECT r.id::text, r.folio, r.kind, r.title, r.status, r.created_at, r.updated_at, d.username AS drafted_by, a.username AS approved_by "
        "FROM reporting.reports r JOIN iam.users d ON d.id = r.drafted_by LEFT JOIN iam.users a ON a.id = r.approved_by "
        "WHERE r.status = ANY(CAST(:s AS text[])) ORDER BY r.created_at DESC LIMIT 100"), {"s": list(statuses)}).all()
    return [dict(r._mapping) for r in rows]


def get_full(report_id):
    r = db.session.execute(text(
        "SELECT r.id::text, r.folio, r.kind, r.title, r.status, r.body, r.return_reason, r.created_at, r.approved_at, "
        "d.username AS drafted_by, a.username AS approved_by, r.drafted_by::text AS drafted_by_id, "
        "s.object_key, s.sha256_signed, s.signer_subject, s.signed_at, s.timestamp_embedded "
        "FROM reporting.reports r JOIN iam.users d ON d.id = r.drafted_by LEFT JOIN iam.users a ON a.id = r.approved_by "
        "LEFT JOIN reporting.signed_documents s ON s.report_id = r.id WHERE r.id = CAST(:i AS uuid)"), {"i": str(report_id)}).first()
    return dict(r._mapping) if r else None
