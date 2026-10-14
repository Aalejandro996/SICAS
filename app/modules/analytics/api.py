from flask import Blueprint, jsonify
from sqlalchemy import text

from app.core.security.rbac import permission_required
from app.extensions import db

bp = Blueprint("analytics", __name__)


@bp.get("/overview")
@permission_required("dashboard:operational", "dashboard:executive")
def overview():
    """Indicadores de control (no contienen datos personales). Los KPIs técnicos de siniestralidad requieren
    además los datasets de siniestros pagados y gastos (pendiente); ver docs/CALCULOS.md."""
    sev = db.session.execute(text("SELECT severity, count(*) n FROM engine.findings WHERE status IN ('OPEN','IN_REVIEW','ESCALATED') GROUP BY 1")).all()
    jobs = db.session.execute(text("SELECT status, count(*) n, coalesce(sum(rows_processed),0) rows, "
                                   "count(*) FILTER (WHERE reconciled IS FALSE) unreconciled FROM insurance.ingestion_jobs GROUP BY 1")).all()
    return jsonify(open_findings_by_severity={r.severity: r.n for r in sev},
                   ingestion=[dict(r._mapping) for r in jobs])

from .contralor_api import register_contralor_routes
register_contralor_routes(bp)
