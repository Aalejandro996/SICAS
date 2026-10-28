"""API del informe general de auditorías.

Flujo: Auditor genera (DRAFT) -> firma y envía al Jefe (IN_REVIEW) -> el Jefe de Auditoría de su dominio aprueba
(APPROVED, distribuido a Gerencia y Contralor) o devuelve (RETURNED, el Auditor regenera y vuelve a firmar).
El informe se emite con las iniciales del Auditor (nombre y apellido); quien aprueba (Jefe, Gerencia y Contralor) estampa la firma
escaneada registrada en SICAS. Firma y aprobaciones quedan atadas al SHA-256 del contenido.
"""
from __future__ import annotations

import json
from datetime import date

from flask import Blueprint, Response, current_app, g, jsonify, request

from app.core.audit.audit_service import audit as log
from app.core.security.rbac import permission_required
from app.modules.engagement import api as eng
from app.modules.engagement import repositories as repo
from app.modules.engagement.report_builder import body_hash, initials_of
from app.modules.notifications import service as notify

from . import content, pdf, service

bp = Blueprint("general_reports", __name__)
READ = ("general_report:create", "general_report:review", "general_report:read_approved")
STATUS_LABEL = {"DRAFT": "Borrador", "IN_REVIEW": "En revisión del Jefe", "RETURNED": "Devuelto", "APPROVED": "Aprobado y distribuido"}
AUDIT_KINDS = ("OPERATIVA", "ESPECIAL", "ADMINISTRATIVA", "FINANCIERA")


NO_SIGNATURE = ("No tiene firma escaneada registrada: el Administrador del Sistema debe cargarla en «Usuarios › Firmas» "
                "antes de que usted apruebe el informe")


def err(msg, code=400):
    return jsonify(error=msg), code


def _perms():
    return set(g.claims.get("perms", []))


def _roles():
    return set(g.claims.get("roles", []))


def _role_label():
    from app.core.security.permissions import ROLE_LABELS
    return ", ".join(ROLE_LABELS.get(r, r) for r in sorted(_roles())) or "Usuario"


def creator_domain():
    """Dominio de las auditorías que puede consolidar el Auditor."""
    p = _perms()
    if "audit:systems_manage" in p and "audit:financial_manage" not in p:
        return "SISTEMAS"
    if "audit:financial_manage" in p:
        return "FINANCIERA"
    return "GENERAL"


def review_domains():
    p = _perms()
    if "general_report:review" not in p:
        return set()
    d = set()
    if "audit:financial_review" in p:
        d |= {"FINANCIERA", "GENERAL"}
    if "audit:systems_review" in p:
        d.add("SISTEMAS")
    return d


def _filters(src):
    def day(name):
        v = str(src.get(name) or "").strip()
        return date.fromisoformat(v[:10]).isoformat() if v else None
    kind = str(src.get("audit_kind") or "").upper()
    unit_kind = str(src.get("unit_kind") or "").upper()
    status = str(src.get("status") or "").upper()
    phase = str(src.get("phase") or "").upper()
    unit = str(src.get("unit_id") or "")
    return {"phase": phase if phase in content.ELIGIBLE_PHASES else None, "audit_kind": kind if kind in AUDIT_KINDS else None,
            "unit_id": int(unit) if unit.isdigit() else None, "unit_kind": unit_kind if unit_kind in ("SUCURSAL", "UNIDAD") else None,
            "status": status if status in ("IN_PROGRESS", "CLOSED") else None, "from": day("from"), "to": day("to"),
            "q": str(src.get("q") or "").strip()[:60] or None}


def _filters_text(f, unit_name=None):
    parts = [f"fase de {content.PHASE_LABEL[f['phase']].lower()}" if f.get("phase") else "fases de documentación e informe",
             f"tipo {content.KIND_LABEL[f['audit_kind']].lower()}" if f.get("audit_kind") else None,
             f"unidad {unit_name}" if unit_name else None,
             {"SUCURSAL": "sucursales", "UNIDAD": "unidades administrativas"}.get(f.get("unit_kind")),
             {"IN_PROGRESS": "en curso", "CLOSED": "cerradas"}.get(f.get("status")),
             f"períodos desde {f['from']}" if f.get("from") else None, f"hasta {f['to']}" if f.get("to") else None,
             f"búsqueda «{f['q']}»" if f.get("q") else None]
    return ", ".join(p for p in parts if p) + " (auditorías seleccionadas por el Auditor)"


@bp.get("/candidates")
@permission_required("general_report:create")
def candidates():
    try:
        f = _filters(request.args)
    except ValueError:
        return err("Fecha inválida (AAAA-MM-DD)")
    domain = creator_domain()
    return jsonify(audits=service.candidates({domain}, f, eng.me()), units=service.units({domain}, eng.me()), domain=domain,
                   phases=list(content.ELIGIBLE_PHASES), max_audits=content.MAX_AUDITS)


def _build(domain, title, objective, audit_ids, f, code, revision=1, author=None):
    """Lee las auditorías elegibles y arma el cuerpo con el motor de reglas. Devuelve (cuerpo, ids usados, ids descartados)."""
    eligible = {a["id"]: a for a in service.candidates({domain}, {}, eng.me())}
    used, dropped, data = [], [], []
    for aid in audit_ids:
        a = repo.get_audit(aid) if aid in eligible else None
        if a is None:
            dropped.append(aid); continue
        used.append(aid)
        data.append(service.audit_data(a, eng.thresholds, eng.overall_for))
    if not data:
        return None, used, dropped
    unit_name = next((a["unit_name"] for a in data if f.get("unit_id")), None)
    body = content.build(audits=data, catalog=service.catalog(domain), company=repo.company() or current_app.config["COMPANY_NAME"],
                         domain=domain, title=title, code=code, author=author, filters_text=_filters_text(f, unit_name),
                         today=date.today(), objective=objective, revision=revision)
    return json.loads(json.dumps(body, default=str)), used, dropped


def _ids(raw):
    ids = list(dict.fromkeys(str(i) for i in (raw or []) if i))
    if not ids:
        raise ValueError("Seleccione al menos una auditoría")
    if len(ids) > content.MAX_AUDITS:
        raise ValueError(f"Seleccione como máximo {content.MAX_AUDITS} auditorías")
    return ids


@bp.post("")
@permission_required("general_report:create")
def create():
    d = request.get_json(silent=True) or {}
    title = str(d.get("title") or "").strip()
    objective = str(d.get("objective") or "").strip()[:600] or None
    if not 5 <= len(title) <= 200:
        return err("Título: entre 5 y 200 caracteres")
    try:
        ids, f = _ids(d.get("audit_ids")), _filters(d.get("filters") or {})
    except ValueError as ex:
        return err(str(ex))
    domain = creator_domain()
    user = (repo.user_brief(eng.me()) or {})
    author = {"name": user.get("name") or g.claims.get("username"), "role": _role_label()}
    code = service.next_code(domain, date.today().year)
    body, used, dropped = _build(domain, title, objective, ids, f, code, author=author)
    if body is None:
        return err("Ninguna de las auditorías seleccionadas es suya (de su equipo) y está en fase de Documentación o de Informe", 409)
    sha = body_hash(body)
    rid = service.create(domain, title, {**f, "objective": objective}, used, body, sha, eng.me(), _role_label())
    log("GENERAL_REPORT_GENERATED", entity_type="general_report", entity_id=rid,
        after_data={"code": code, "auditorias": len(used), "sha256": sha}, request_id=g.request_id)
    return jsonify(id=rid, code=code, dropped=dropped), 201


@bp.get("")
@permission_required(*READ)
def search():
    p = _perms()
    rows = service.search(eng.me(), review_domains(), "general_report:read_approved" in p, "general_report:create" in p)
    for r in rows:
        r["status_label"] = STATUS_LABEL.get(r["status"], r["status"])
    return jsonify(reports=rows, can_create="general_report:create" in p)


def _load(rid):
    rep = service.get(rid)
    if rep is None:
        return None, err("No encontrado", 404)
    p, uid = _perms(), eng.me()
    mine = rep["created_by"] == uid
    jefe = rep["audit_domain"] in review_domains() and rep["status"] != "DRAFT"
    reader = "general_report:read_approved" in p and rep["status"] == "APPROVED"
    if not (mine or jefe or reader):
        return None, err("No encontrado", 404)
    return rep, None


def _can(rep):
    p, uid = _perms(), eng.me()
    mine = rep["created_by"] == uid
    jefe = rep["audit_domain"] in review_domains() and uid != rep["created_by"]
    acked = any(a["user_id"] == uid for a in service.acks(rep["id"]))
    return {
        "regenerate": mine and rep["status"] in ("DRAFT", "RETURNED"),
        "sign": mine and rep["status"] in ("DRAFT", "RETURNED") and "general_report:create" in p,
        "approve": jefe and rep["status"] == "IN_REVIEW",
        "return": jefe and rep["status"] == "IN_REVIEW",
        "acknowledge": "general_report:read_approved" in p and rep["status"] == "APPROVED" and not acked,
    }


@bp.get("/<uuid:rid>")
@permission_required(*READ)
def detail(rid):
    rep, e = _load(rid)
    if e:
        return e
    rep["status_label"] = STATUS_LABEL.get(rep["status"], rep["status"])
    return jsonify(report=rep, events=service.events(rep["id"]), acks=service.acks(rep["id"]), can=_can(rep))


def _when(v):
    return v.strftime("%d/%m/%Y %H:%M") if hasattr(v, "strftime") else str(v or "")[:16]


@bp.get("/<uuid:rid>/pdf")
@permission_required(*READ)
def report_pdf(rid):
    rep, e = _load(rid)
    if e:
        return e
    jefe = None
    # Al emitirlo, el informe ya lleva las iniciales del Auditor que lo elaboró (nombre y apellido).
    auditor = {"name": rep["created_by_name"], "initials": initials_of(rep["created_by_name"] or ""),
               "note": (f"Enviado al Jefe el {_when(rep['auditor_signed_at'])}" if rep["auditor_signed_sha256"] == rep["body_sha256"]
                        else f"Emitido el {_when(rep['updated_at'])}")}
    if rep["status"] == "APPROVED" and rep["jefe_sha256"] == rep["body_sha256"]:
        jefe = {"name": rep["jefe_name"], "note": f"Revisado y aprobado el {_when(rep['jefe_at'])}",
                "image": service.signature_by_sha(rep["jefe_by"], rep["jefe_signature_sha256"])}
    from app.core.security.permissions import ROLE_LABELS
    acks = [{"name": a["name"], "role": ROLE_LABELS.get(a["role"], a["role"].capitalize()), "date": _when(a["created_at"]),
             "image": service.signature_by_sha(a["user_id"], a["signature_sha256"])} for a in service.acks(rep["id"])]
    data = pdf.build_pdf(rep["body"], {"status": rep["status"], "body_sha256": rep["body_sha256"], "auditor": auditor, "jefe": jefe, "acks": acks})
    log("GENERAL_REPORT_PRINTED", entity_type="general_report", entity_id=rep["id"], metadata={"status": rep["status"]}, request_id=g.request_id)
    return Response(data, mimetype="application/pdf", headers={"Content-Disposition": f'inline; filename="{rep["code"]}.pdf"',
                                                              "X-Content-Type-Options": "nosniff"})


@bp.post("/<uuid:rid>/regenerate")
@permission_required("general_report:create")
def regenerate(rid):
    rep, e = _load(rid)
    if e:
        return e
    if not _can(rep)["regenerate"]:
        return err("Solo el Auditor que lo generó lo actualiza, mientras está en borrador o devuelto", 409)
    d = request.get_json(silent=True) or {}
    try:
        ids = _ids(d.get("audit_ids") or rep["audit_ids"])
    except ValueError as ex:
        return err(str(ex))
    f = {k: v for k, v in (rep["filters"] or {}).items() if k != "objective"}
    body, used, dropped = _build(rep["audit_domain"], rep["title"], (rep["filters"] or {}).get("objective"), ids, f, rep["code"],
                                 revision=rep["revision"] + 1, author=rep["body"].get("author"))
    if body is None:
        return err("Ninguna de las auditorías sigue en fase de Documentación o de Informe", 409)
    sha = body_hash(body)
    try:
        service.replace_body(rep, body, sha, used, eng.me(), _role_label())
    except service.StaleState as ex:
        return err(str(ex), 409)
    log("GENERAL_REPORT_REGENERATED", entity_type="general_report", entity_id=rep["id"], after_data={"sha256": sha, "auditorias": len(used)},
        request_id=g.request_id)
    return jsonify(status=rep["status"], dropped=dropped)


def _target(rep):
    return f"#/general-reports/{rep['id']}"


def _notify(label, recipients, rep, event, title, message):
    def emit():
        notify._insert_for_users(recipients, category="REPORT", event_key=notify._event_key("general_report", rep["id"], event, g.request_id),
                                 title=title, message=message, target_path=_target(rep), entity_type="general_report",
                                 entity_id=rep["id"], actor_user_id=eng.me())
    notify._safe_emit(label, emit)


@bp.post("/<uuid:rid>/sign")
@permission_required("general_report:create", step_up=True)
def sign(rid):
    rep, e = _load(rid)
    if e:
        return e
    if not _can(rep)["sign"]:
        return err("Solo el Auditor que lo generó lo firma y envía, mientras está en borrador o devuelto", 409)
    try:
        # El informe ya lleva las iniciales del Auditor; el envío deja constancia del contenido enviado.
        service.transition(rep, "IN_REVIEW", "SIGNED_SENT", eng.me(), _role_label(),
                           auditor_signed_by=eng.me(), auditor_signed_at="now", auditor_signed_sha256=rep["body_sha256"],
                           auditor_signature_sha256=None,
                           jefe_by=None, jefe_at=None, jefe_sha256=None, jefe_signature_sha256=None)
    except service.StaleState as ex:
        return err(str(ex), 409)
    log("GENERAL_REPORT_SIGNED_SENT", entity_type="general_report", entity_id=rep["id"], after_data={"sha256": rep["body_sha256"]},
        request_id=g.request_id)
    role = "JEFE_AUDITORIA_SISTEMAS" if rep["audit_domain"] == "SISTEMAS" else "JEFE_AUDITORIA_FINANCIERA"
    _notify("informe general enviado", notify._role_user_ids([role]), rep, "sent", "Informe general recibido para revisión",
            f"El informe general {rep['code']} fue emitido por el Auditor y está pendiente de su revisión.")
    return jsonify(status="IN_REVIEW", note="Informe enviado al Jefe de Auditoría.")


@bp.post("/<uuid:rid>/approve")
@permission_required("general_report:review", step_up=True)
def approve(rid):
    rep, e = _load(rid)
    if e:
        return e
    if not _can(rep)["approve"]:
        return err("El informe no está pendiente de su revisión", 409)
    if rep["auditor_signed_sha256"] != rep["body_sha256"]:
        return err("La firma del Auditor no corresponde al contenido actual", 409)
    sig = service.signature(eng.me())
    if sig is None:
        return err(NO_SIGNATURE, 409)
    comment = str((request.get_json(silent=True) or {}).get("comment") or "").strip()[:2000] or None
    try:
        service.transition(rep, "APPROVED", "APPROVED", eng.me(), _role_label(), comment=comment,
                           jefe_by=eng.me(), jefe_at="now", jefe_sha256=rep["body_sha256"], jefe_signature_sha256=sig["sha256"])
    except service.StaleState as ex:
        return err(str(ex), 409)
    log("GENERAL_REPORT_APPROVED", entity_type="general_report", entity_id=rep["id"], after_data={"sha256": rep["body_sha256"]},
        request_id=g.request_id)
    _notify("informe general aprobado", notify._role_user_ids(["GERENCIA", "CONTRALOR"]), rep, "approved",
            "Informe general de auditorías aprobado",
            f"El Jefe de Auditoría aprobó el informe general {rep['code']}: estado actual de las unidades evaluadas.")
    _notify("informe general aprobado (auditor)", [rep["created_by"]], rep, "approved-author", "Su informe general fue aprobado",
            f"El informe general {rep['code']} fue aprobado y enviado a Gerencia y al Contralor.")
    return jsonify(status="APPROVED", note="Informe aprobado y enviado a Gerencia y al Contralor.")


@bp.post("/<uuid:rid>/return")
@permission_required("general_report:review")
def return_report(rid):
    rep, e = _load(rid)
    if e:
        return e
    if not _can(rep)["return"]:
        return err("El informe no está pendiente de su revisión", 409)
    comment = str((request.get_json(silent=True) or {}).get("comment") or "").strip()
    if not 10 <= len(comment) <= 2000:
        return err("Indique qué debe corregirse (10 a 2000 caracteres)")
    try:
        service.transition(rep, "RETURNED", "RETURNED", eng.me(), _role_label(), comment=comment,
                           auditor_signed_by=None, auditor_signed_at=None, auditor_signed_sha256=None, auditor_signature_sha256=None)
    except service.StaleState as ex:
        return err(str(ex), 409)
    log("GENERAL_REPORT_RETURNED", entity_type="general_report", entity_id=rep["id"], metadata={"comment": comment}, request_id=g.request_id)
    _notify("informe general devuelto", [rep["created_by"]], rep, "returned", "Informe general devuelto",
            f"El Jefe de Auditoría devolvió el informe general {rep['code']}: {comment[:300]}")
    return jsonify(status="RETURNED")


@bp.post("/<uuid:rid>/acknowledge")
@permission_required("general_report:read_approved", step_up=True)
def acknowledge(rid):
    rep, e = _load(rid)
    if e:
        return e
    if not _can(rep)["acknowledge"]:
        return err("Ya registró la recepción o el informe no está aprobado", 409)
    sig = service.signature(eng.me())
    if sig is None:
        return err(NO_SIGNATURE, 409)
    role = "CONTRALOR" if "CONTRALOR" in _roles() else "GERENCIA"
    note = str((request.get_json(silent=True) or {}).get("note") or "").strip()[:1000] or None
    service.acknowledge(rep, eng.me(), role, note, sig["sha256"], _role_label())
    log("GENERAL_REPORT_ACKNOWLEDGED", entity_type="general_report", entity_id=rep["id"], metadata={"role": role}, request_id=g.request_id)
    return jsonify(status="OK")
