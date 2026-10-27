"""API del módulo «Evaluación TI de sucursales» (Jefe de Auditoría de Sistemas; consulta del Contralor)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, Response, current_app, g, jsonify, request

from app.core.audit.audit_service import audit as log
from app.core.security.rbac import permission_required

from . import report, service

bp = Blueprint("ti_branches", __name__)
CRITICALITIES = ("CRITICA", "ALTA", "MEDIA", "BAJA")


def _filters():
    a = request.args

    def day(name):
        v = (a.get(name) or "").strip()
        return date.fromisoformat(v) if v else None

    crit = (a.get("criticality") or "").upper() or None
    sod = (a.get("sod") or "").upper() or None
    unit = a.get("unit_id")
    return {"date_from": day("from"), "date_to": day("to"), "unit_id": int(unit) if unit and unit.isdigit() else None,
            "criticality": crit if crit in CRITICALITIES else None, "sod": sod if sod in ("SI", "NO") else None,
            "latest": (a.get("history") or "") != "1"}


@bp.get("")
@permission_required("ti_branch:read")
def search():
    try:
        f = _filters()
    except ValueError:
        return jsonify(error="Fecha inválida (use AAAA-MM-DD)"), 400
    return jsonify(**service.search(**f), branches=service.branches(), can_report="ti_branch:report" in g.claims.get("perms", []))


@bp.get("/<uuid:audit_id>")
@permission_required("ti_branch:read")
def detail(audit_id):
    d = service.detail(audit_id)
    return (jsonify(d), 200) if d else (jsonify(error="No encontrada"), 404)


@bp.get("/report.pdf")
@permission_required("ti_branch:report")
def report_pdf():
    try:
        f = _filters()
    except ValueError:
        return jsonify(error="Fecha inválida (use AAAA-MM-DD)"), 400
    data = service.search(**f)
    unit = next((b["unit_name"] for b in service.branches() if b["unit_id"] == f["unit_id"]), None)
    parts = [f"desde {f['date_from']:%d/%m/%Y}" if f["date_from"] else None, f"hasta {f['date_to']:%d/%m/%Y}" if f["date_to"] else None,
             f"sucursal {unit}" if unit else None, f"criticidad {report.CRIT_LABEL[f['criticality']].lower()}" if f["criticality"] else None,
             {"SI": "con conflictos de perfiles", "NO": "sin conflictos de perfiles"}.get(f["sod"]),
             "historial completo" if not f["latest"] else "última evaluación de cada sucursal"]
    pdf = report.build(data, {"text": ", ".join(p for p in parts if p)}, service.sudeaseg_reference(),
                       current_app.config.get("COMPANY_NAME", "Aseguradora"), g.claims.get("username", ""))
    log("TI_BRANCH_REPORT", entity_type="ti_branch", entity_id="report", metadata={"evaluaciones": len(data["rows"]), "filtros": parts},
        request_id=getattr(g, "request_id", None))
    name = f"Evaluacion_TI_sucursales_{date.today():%Y%m%d}" + (f"_{unit.replace(' ', '_')}" if unit else "") + ".pdf"
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})
