"""Rutas del dashboard privado del Contralor y administración de KPI."""
from __future__ import annotations

from flask import Response, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import IntegrityError

from app.core.security.rbac import permission_required

from . import contralor_service as service


def register_contralor_routes(bp):
    @bp.get("/contralor/options")
    @permission_required("dashboard:contralor")
    def contralor_options():
        return jsonify(**service.get_options(), metrics=service.METRICS)

    @bp.get("/contralor/overview")
    @permission_required("dashboard:contralor")
    def contralor_overview():
        try:
            filters = service.parse_filters(request.args)
            return jsonify(service.get_dashboard_data(filters))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.get("/contralor/kpis")
    @permission_required("dashboard:contralor")
    def contralor_list_kpis():
        return jsonify(kpis=service.list_kpis(include_inactive=request.args.get("all") == "1"),
                       metrics=service.METRICS,
                       periodicities=sorted(service.PERIODICITIES))

    @bp.post("/contralor/kpis")
    @permission_required("dashboard:contralor", "kpi:manage", require_all=True)
    def contralor_create_kpi():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Se esperaba un objeto JSON."), 400
        try:
            identity = get_jwt_identity()
            created = service.create_kpi(payload, str(identity))
            return jsonify(kpi=created), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except IntegrityError:
            from app.extensions import db
            db.session.rollback()
            return jsonify(error="No se pudo guardar el KPI. Verifique que la unidad o el auditor existan."), 400

    @bp.patch("/contralor/kpis/<uuid:kpi_id>")
    @permission_required("dashboard:contralor", "kpi:manage", require_all=True)
    def contralor_update_kpi(kpi_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not payload:
            return jsonify(error="Se esperaba un objeto JSON con cambios."), 400
        try:
            updated = service.update_kpi(str(kpi_id), payload, str(get_jwt_identity()))
            return jsonify(kpi=updated)
        except LookupError as exc:
            return jsonify(error=str(exc)), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except IntegrityError:
            from app.extensions import db
            db.session.rollback()
            return jsonify(error="No se pudo actualizar el KPI. Verifique la unidad o el auditor."), 400

    @bp.get("/activity/options")
    @permission_required("audit:manage")
    def activity_options():
        try:
            return jsonify(**service.get_activity_options(str(get_jwt_identity())))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.post("/activity/start")
    @permission_required("audit:manage")
    def activity_start():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not payload.get("audit_id"):
            return jsonify(error="Seleccione una auditoría asignada."), 400
        try:
            session = service.start_activity_session(str(payload["audit_id"]), str(get_jwt_identity()))
            return jsonify(session=session), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except IntegrityError:
            from app.extensions import db
            db.session.rollback()
            return jsonify(error="No se pudo iniciar la sesión. Compruebe si ya tiene otra activa."), 409

    @bp.post("/activity/pause")
    @permission_required("audit:manage")
    def activity_pause():
        return _activity_transition(service, "PAUSE")

    @bp.post("/activity/resume")
    @permission_required("audit:manage")
    def activity_resume():
        return _activity_transition(service, "RESUME")

    @bp.post("/activity/stop")
    @permission_required("audit:manage")
    def activity_stop():
        return _activity_transition(service, "STOP")

    def _activity_transition(activity_service, action):
        try:
            session = activity_service.transition_activity_session(action, str(get_jwt_identity()))
            return jsonify(session=session)
        except LookupError as exc:
            return jsonify(error=str(exc)), 404
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.get("/contralor/snapshots")
    @permission_required("dashboard:contralor")
    def contralor_snapshots():
        try:
            limit = int(request.args.get("limit", "12"))
            return jsonify(snapshots=service.list_dashboard_snapshots(limit))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.post("/contralor/snapshots")
    @permission_required("dashboard:contralor", "kpi:manage", require_all=True)
    def contralor_create_snapshot():
        try:
            filters = service.parse_filters(request.args)
            snapshot = service.create_dashboard_snapshot(filters, str(get_jwt_identity()), source="MANUAL")
            return jsonify(snapshot=snapshot), 201
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.get("/contralor/kpis/<uuid:kpi_id>/history")
    @permission_required("dashboard:contralor")
    def contralor_kpi_history(kpi_id):
        try:
            limit = int(request.args.get("limit", "24"))
            return jsonify(measurements=service.get_kpi_measurement_history(str(kpi_id), limit))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.get("/contralor/export.pdf")
    @permission_required("dashboard:contralor", "kpi:export", require_all=True)
    def contralor_export_pdf():
        try:
            filters = service.parse_filters(request.args)
            data = service.get_dashboard_data(filters)
            kpis = service.list_kpis()
            out = service.export_pdf_report(data, kpis)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except ImportError:
            return jsonify(error="La dependencia de generación PDF no está instalada. Reconstruya la API con requirements/base.txt actualizado."), 503
        filename = f"SICAS_dashboard_contralor_{filters['start_date'].isoformat()}_{filters['end_date'].isoformat()}.pdf"
        return send_file(out, mimetype="application/pdf", as_attachment=True, download_name=filename, max_age=0)

    @bp.get("/contralor/report")
    @permission_required("dashboard:contralor")
    def contralor_print_report():
        try:
            filters = service.parse_filters(request.args)
            data = service.get_dashboard_data(filters)
            kpis = service.list_kpis()
            return Response(service.render_print_report(data, kpis), mimetype="text/html; charset=utf-8",
                            headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    @bp.get("/contralor/export.xlsx")
    @permission_required("dashboard:contralor", "kpi:export", require_all=True)
    def contralor_export():
        try:
            filters = service.parse_filters(request.args)
            data = service.get_dashboard_data(filters)
            kpis = service.list_kpis()
            data["historical_snapshots"] = service.list_dashboard_snapshots(12)
            out = service.export_workbook(data, kpis)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        filename = f"SICAS_dashboard_contralor_{filters['start_date'].isoformat()}_{filters['end_date'].isoformat()}.xlsx"
        return send_file(out, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=filename, max_age=0)
