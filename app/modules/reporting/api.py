"""Informes: redactar -> enviar -> aprobar (otra persona) -> firmar (MFA reciente) -> descargar y verificar."""
import hashlib
import uuid
from datetime import date

from flask import Blueprint, Response, current_app, g, jsonify, request
from flask_jwt_extended import get_jwt_identity

from app.core.audit.audit_service import audit
from app.core.security.rbac import permission_required

from . import drafting, storage
from . import repositories as repo
from . import workflow as wf
from .dictamen_pdf import build_dictamen_pdf
from .signing import service as signing
from .signing import verify as sigverify

bp = Blueprint("reporting", __name__)
FINAL = ("APPROVED", "SIGNED")


def _can_see(row) -> bool:
    perms = set(g.claims.get("perms", []))
    return "report:read" in perms or ("report:read_approved" in perms and row["status"] in FINAL)


# ------------------------------------------------------------------ redacción y consulta
@bp.post("")
@permission_required("report:draft")
def create():
    d = request.get_json(silent=True) or {}
    try:
        kind, title, conclusion, ids = drafting.validate_draft(d.get("kind"), d.get("title"), d.get("conclusion"), d.get("finding_ids", []))
    except drafting.DraftError as e:
        return jsonify(error=str(e)), 400
    findings = repo.fetch_findings(ids)
    if len(findings) != len(ids):
        return jsonify(error="Algún hallazgo no existe"), 400
    rid, today = uuid.uuid4(), date.today()
    folio = drafting.make_folio(kind, today.year, repo.next_folio_number())
    body = drafting.build_body(folio=folio, kind=kind, title=title, company=current_app.config["COMPANY_NAME"],
                               author=g.claims.get("username", ""), on=today, findings=findings, conclusion=conclusion)
    repo.create_report(rid, folio, kind, title, body, get_jwt_identity())
    audit("REPORT_DRAFTED", entity_type="report", entity_id=str(rid), after_data={"folio": folio, "findings": ids}, request_id=g.request_id)
    return jsonify(id=str(rid), folio=folio, status="DRAFT"), 201


@bp.get("")
@permission_required("report:read", "report:read_approved")
def list_all():
    full = "report:read" in set(g.claims.get("perms", []))
    st = request.args.get("status")
    allowed = ["DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "SIGNED"] if full else list(FINAL)
    statuses = [st.upper()] if st and st.upper() in allowed else allowed
    return jsonify(reports=repo.list_reports(statuses))


@bp.get("/<uuid:report_id>")
@permission_required("report:read", "report:read_approved")
def get_one(report_id):
    row = repo.get_full(report_id)
    if row is None or not _can_see(row):
        return jsonify(error="No encontrado"), 404
    row.pop("object_key", None)                               # no se expone la ubicación interna
    return jsonify(report=row)


@bp.put("/<uuid:report_id>")
@permission_required("report:draft")
def update(report_id):
    row = repo.get_full(report_id)
    if row is None:
        return jsonify(error="No encontrado"), 404
    if row["drafted_by_id"] != get_jwt_identity():
        return jsonify(error="Solo el redactor puede modificar el borrador"), 403
    if row["status"] not in ("DRAFT", "RETURNED"):
        return jsonify(error="El informe ya no es editable"), 409
    d = request.get_json(silent=True) or {}
    try:
        kind, title, conclusion, ids = drafting.validate_draft(row["kind"], d.get("title"), d.get("conclusion"), d.get("finding_ids", []))
    except drafting.DraftError as e:
        return jsonify(error=str(e)), 400
    findings = repo.fetch_findings(ids)
    if len(findings) != len(ids):
        return jsonify(error="Algún hallazgo no existe"), 400
    old = row["body"]
    body = drafting.build_body(folio=old["folio"], kind=kind, title=title, company=old["company"], author=old["author"],
                               on=date.today(), findings=findings, conclusion=conclusion)
    repo.update_draft(report_id, title, body)
    audit("REPORT_EDITED", entity_type="report", entity_id=str(report_id), request_id=g.request_id)
    return jsonify(status=row["status"])


@bp.get("/<uuid:report_id>/preview")
@permission_required("report:read")
def preview(report_id):
    """PDF de vista previa (sin firma) para revisar antes de aprobar."""
    row = repo.get_full(report_id)
    if row is None:
        return jsonify(error="No encontrado"), 404
    pdf = build_dictamen_pdf({**row["body"], "body_sha256": wf.body_hash(row["body"])})
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="vista_previa_{row["folio"]}.pdf"'})


@bp.get("/<uuid:report_id>/download")
@permission_required("report:read", "report:read_approved")
def download(report_id):
    row = repo.get_full(report_id)
    if row is None or not _can_see(row) or row["status"] != "SIGNED" or not row.get("object_key"):
        return jsonify(error="No encontrado"), 404
    try:
        data = storage.get_signed(row["object_key"])
    except Exception:  # noqa: BLE001
        return jsonify(error="No fue posible recuperar el documento"), 500
    if hashlib.sha256(data).hexdigest() != row["sha256_signed"]:       # integridad contra el registro de solo inserción
        audit("SIGNED_DOCUMENT_TAMPERED", outcome="FAILURE", entity_type="report", entity_id=str(report_id), request_id=g.request_id)
        return jsonify(error="El documento almacenado no coincide con su huella registrada"), 500
    audit("REPORT_DOWNLOADED", entity_type="report", entity_id=str(report_id), request_id=g.request_id)
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{row["folio"]}_firmado.pdf"'})


# ------------------------------------------------------------------ flujo
@bp.post("/<uuid:report_id>/submit")
@permission_required("report:submit")
def submit(report_id):
    r = repo.get_report(report_id)
    if r is None:
        return jsonify(error="No encontrado"), 404
    try:
        wf.can_submit(r, get_jwt_identity())
    except wf.WorkflowError as e:
        return jsonify(error=str(e)), 409
    repo.mark_submitted(report_id)
    audit("REPORT_SUBMITTED", entity_type="report", entity_id=str(report_id), request_id=g.request_id)
    return jsonify(status=wf.SUBMITTED)


@bp.post("/<uuid:report_id>/approve")
@permission_required("report:approve", step_up=True)
def approve(report_id):
    r = repo.get_report(report_id)
    if r is None:
        return jsonify(error="No encontrado"), 404
    try:
        wf.can_approve(r, get_jwt_identity())
    except wf.WorkflowError as e:
        audit("REPORT_APPROVE_REJECTED", outcome="DENIED", entity_type="report", entity_id=str(report_id),
              metadata={"reason": str(e)}, request_id=g.request_id)
        return jsonify(error=str(e)), 409
    digest = wf.body_hash(r.body)
    repo.mark_approved(report_id, get_jwt_identity(), digest)
    audit("REPORT_APPROVED", entity_type="report", entity_id=str(report_id), after_data={"body_sha256": digest}, request_id=g.request_id)
    return jsonify(status=wf.APPROVED, body_sha256=digest)


@bp.post("/<uuid:report_id>/return")
@permission_required("report:approve")
def return_to_draft(report_id):
    reason = (request.get_json(silent=True) or {}).get("reason", "").strip()
    if len(reason) < 10:
        return jsonify(error="Indique el motivo (mínimo 10 caracteres)"), 400
    r = repo.get_report(report_id)
    if r is None:
        return jsonify(error="No encontrado"), 404
    if r.status != wf.SUBMITTED:
        return jsonify(error="Solo se pueden devolver informes enviados"), 409
    if r.drafted_by == get_jwt_identity():
        return jsonify(error="Doble control: no puede resolver su propio informe"), 409
    repo.mark_returned(report_id, reason)
    audit("REPORT_RETURNED", entity_type="report", entity_id=str(report_id), metadata={"reason": reason}, request_id=g.request_id)
    return jsonify(status=wf.RETURNED)


@bp.post("/<uuid:report_id>/sign")
@permission_required("report:sign", step_up=True)
def sign(report_id):
    r = repo.get_report(report_id)
    if r is None:
        return jsonify(error="No encontrado"), 404
    actor = get_jwt_identity()
    try:
        wf.can_sign(r, actor)
    except wf.WorkflowError as e:
        audit("REPORT_SIGN_REJECTED", outcome="DENIED", entity_type="report", entity_id=str(report_id),
              metadata={"reason": str(e)}, request_id=g.request_id)
        return jsonify(error=str(e)), 409

    cfg = current_app.config
    try:
        pdf = build_dictamen_pdf({**r.body, "body_sha256": r.approved_body_sha256})
        signed = signing.sign_pdf(pdf, signing.load_signer(cfg), reason="Dictamen de Contraloría",
                                  location=cfg.get("SIGNING_LOCATION", "Venezuela"), signer_name=g.claims.get("username", actor),
                                  tsa_url=cfg.get("TSA_URL"))
        object_key = f"signed/{report_id}/v1.pdf"
        storage.put_signed(object_key, signed.pdf_bytes)           # primero se guarda; solo entonces se registra
    except Exception as e:  # noqa: BLE001
        audit("REPORT_SIGN_FAILED", outcome="FAILURE", entity_type="report", entity_id=str(report_id),
              metadata={"error": type(e).__name__}, request_id=g.request_id)
        detail = f" ({e})" if cfg.get("ENV") == "dev" else ""
        return jsonify(error="No fue posible firmar el documento" + detail), 500
    doc_id = repo.register_signed(report_id, actor, signed, object_key)
    audit("REPORT_SIGNED", entity_type="report", entity_id=str(report_id),
          after_data={"signed_document_id": doc_id, "sha256_signed": signed.sha256_signed, "cert_serial": signed.cert_serial,
                      "timestamp": signed.timestamp_embedded}, request_id=g.request_id)
    return jsonify(status=wf.SIGNED, signed_document_id=doc_id, sha256_signed=signed.sha256_signed,
                   timestamp_embedded=signed.timestamp_embedded)


@bp.post("/verify")
@permission_required("report:verify_signature")
def verify():
    f = request.files.get("file")
    if f is None:
        return jsonify(error="Adjunte un PDF"), 400
    data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    known = repo.find_signed_by_hash(digest)
    try:
        signatures = sigverify.verify_pdf(data, current_app.config.get("SIGNING_TRUST_ROOTS_PEM"))
    except Exception:  # noqa: BLE001 - PDF corrupto o sin firmas
        return jsonify(error="No se pudo analizar el PDF"), 422
    audit("REPORT_VERIFIED", entity_type="pdf", entity_id=digest, after_data={"signatures": len(signatures)}, request_id=g.request_id)
    return jsonify(signatures=signatures, registered=bool(known), registered_report_id=str(known.report_id) if known else None)
