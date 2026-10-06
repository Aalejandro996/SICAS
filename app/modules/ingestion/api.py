import hashlib
import uuid

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.core.audit.audit_service import audit
from app.core.security.rbac import permission_required
from app.extensions import limiter
from app.tasks.ingestion_tasks import process_ingestion_job

from . import repositories as repo
from .validators import DATASETS
from .storage import save_encrypted

bp = Blueprint("ingestion", __name__)
ALLOWED = {".csv", ".txt"}


@bp.post("/uploads")
@limiter.limit("10/hour")
@permission_required("ingestion:upload")
def upload():
    dataset, f = request.form.get("dataset"), request.files.get("file")
    if dataset not in DATASETS or f is None or not f.filename:
        return jsonify(error="Parámetros inválidos"), 400
    ext = "." + f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ALLOWED:
        return jsonify(error="Formato no permitido"), 415

    sha = hashlib.sha256()
    for chunk in iter(lambda: f.stream.read(1024 * 1024), b""):
        sha.update(chunk)
    f.stream.seek(0)
    digest = sha.hexdigest()
    if repo.exists_by_hash(digest, dataset):
        return jsonify(error="Archivo ya procesado", sha256=digest), 409

    job_id = uuid.uuid4()
    object_key = save_encrypted(f.stream, job_id)
    repo.create_job(job_id, dataset, digest, object_key, uploaded_by=get_jwt_identity())
    process_ingestion_job.apply_async(args=[str(job_id)], queue="ingestion")
    audit(action="INGESTION_UPLOADED", entity_type="ingestion_job", entity_id=str(job_id),
          after_data={"dataset": dataset, "sha256": digest}, request_id=g.request_id)
    return jsonify(job_id=str(job_id), status="QUEUED"), 202


@bp.get("/uploads/<uuid:job_id>")
@permission_required("ingestion:read")
def status(job_id):
    job = repo.get_job(job_id)
    if job is None:
        return jsonify(error="No encontrado"), 404
    return jsonify(job_id=str(job.id), status=job.status, processed=job.rows_processed,
                   rejected=job.rows_rejected, total=job.rows_total)


# ------------------------------------------------------------------ listados y plantillas
from flask import Response
from sqlalchemy import text

from app.extensions import db
from .validators import SPECS

_SAMPLE = {
    "policies": ["POL-0001", "V12345678", "ABC12D", "AUTO", "2026-01-01", "2026-12-31", "50000", "1200", "USD"],
    "claims": ["SIN-0001", "POL-0001", "COLISION", "2026-03-15", "2026-03-16", "2500.50", "USD"],
    "reserves": ["CLAIM", "AUTO", "POL-0001", "SIN-0001", "2026-09-01", "2500.50", "50000", "USD"],
    "payments": ["PAG-0001", "POL-0001", "V12345678", "1200", "USD", "TRANSFER", "2026-01-02"],
}


@bp.get("/templates/<dataset>")
@permission_required("ingestion:read", "ingestion:upload")
def template(dataset):
    if dataset not in SPECS:
        return jsonify(error="Dataset inexistente"), 404
    body = ",".join(SPECS[dataset]["cols"]) + "\n" + ",".join(_SAMPLE[dataset]) + "\n"
    return Response(body, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=plantilla_{dataset}.csv"})


@bp.get("/uploads")
@permission_required("ingestion:read")
def list_jobs():
    rows = db.session.execute(text(
        "SELECT j.id::text, j.dataset, j.status, j.rows_processed, j.rows_rejected, j.reconciled, j.control_rows, "
        "j.created_at, j.finished_at, u.username AS uploaded_by FROM insurance.ingestion_jobs j "
        "LEFT JOIN iam.users u ON u.id = j.uploaded_by ORDER BY j.created_at DESC LIMIT 30")).all()
    return jsonify(jobs=[dict(r._mapping) for r in rows])


@bp.get("/uploads/<uuid:job_id>/rejects")
@permission_required("ingestion:review_rejects")
def rejects(job_id):
    rows = db.session.execute(text("SELECT line_no, errors FROM insurance.ingestion_rejects WHERE job_id=CAST(:j AS uuid) "
                                   "ORDER BY line_no LIMIT 300"), {"j": str(job_id)}).all()
    return jsonify(rejects=[{"line": r.line_no, "errors": r.errors} for r in rows])
