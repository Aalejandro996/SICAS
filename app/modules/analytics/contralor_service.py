"""Servicios agregados para el dashboard de Contraloría.

Las consultas devuelven métricas agregadas; no exponen datos personales de asegurados.
Las métricas configurables se eligen de un catálogo cerrado, nunca de SQL libre.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import html
import json
from io import BytesIO
from math import isfinite
from typing import Any
from uuid import UUID

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import text

from app.extensions import db

CLOSED_STATUSES = ("CLOSED", "COMPLETED", "SIGNED", "CERRADO", "CERRADA")
IN_PROGRESS_STATUSES = ("IN_PROGRESS", "IN PROGRESS", "EN_CURSO", "EN CURSO", "RUNNING")
OPEN_OBSERVATION_STATUSES = ("", "PENDING", "PENDIENTE", "OPEN", "ABIERTO", "IN_PROGRESS", "EN_CURSO")

RISK_CASE = """CASE
    WHEN upper(trim(coalesce(o.risk, ''))) IN ('CRITICAL', 'CRITICO', 'CRÍTICO', 'CRITICA', 'CRÍTICA') THEN 'CRITICAL'
    WHEN upper(trim(coalesce(o.risk, ''))) IN ('HIGH', 'ALTO', 'ALTA') THEN 'HIGH'
    WHEN upper(trim(coalesce(o.risk, ''))) IN ('MEDIUM', 'MEDIO', 'MEDIA') THEN 'MEDIUM'
    WHEN upper(trim(coalesce(o.risk, ''))) IN ('LOW', 'BAJO', 'BAJA') THEN 'LOW'
    WHEN trim(coalesce(o.risk, '')) = '' THEN 'UNSPECIFIED'
    ELSE 'OTHER'
END"""

CLOSED_SQL = "upper(coalesce(s.status, '')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')"
IN_PROGRESS_SQL = "upper(coalesce(s.status, '')) IN ('IN_PROGRESS','IN PROGRESS','EN_CURSO','EN CURSO','RUNNING')"

SCOPE_CTE = f"""WITH audit_scope AS (
    SELECT
        a.id, a.code, a.status, a.phase, a.audit_domain, a.created_at, a.pac_sent_at,
        f.unit_id,
        coalesce(nullif(btrim(u.name), ''), 'Sin unidad') AS unit_name,
        coalesce(nullif(btrim(u.code), ''), '') AS unit_code,
        lp.last_changed_at,
        CASE
          WHEN upper(coalesce(a.status, '')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
            THEN CASE WHEN a.pac_sent_at IS NULL THEN NULL
                      ELSE greatest(engagement.business_seconds(a.created_at, a.pac_sent_at) / 32400.0, 0) END
          ELSE greatest(engagement.business_seconds(a.created_at, CURRENT_TIMESTAMP) / 32400.0, 0)
        END AS elapsed_days
    FROM engagement.audits a
    LEFT JOIN engagement.files f ON f.id = a.file_id
    LEFT JOIN engagement.units u ON u.id = f.unit_id
    LEFT JOIN LATERAL (
        SELECT max(pl.changed_at) AS last_changed_at
        FROM engagement.phase_log pl
        WHERE pl.audit_id = a.id
    ) lp ON TRUE
    WHERE a.status <> 'ANULADA'
      AND a.created_at >= :start_at
      AND a.created_at < :end_before
      AND (CAST(:unit_id AS integer) IS NULL OR f.unit_id = CAST(:unit_id AS integer))
      AND (CAST(:audit_domain AS text) IS NULL OR upper(coalesce(a.audit_domain, '')) = CAST(:audit_domain AS text))
      AND (CAST(:auditor_id AS uuid) IS NULL OR EXISTS (
          SELECT 1 FROM engagement.team t
          WHERE t.audit_id = a.id AND t.user_id = CAST(:auditor_id AS uuid)
      ))
)"""

OBS_CTE = f"""WITH observed_audits AS (
    SELECT a.id, f.unit_id,
           coalesce(nullif(btrim(u.name), ''), 'Sin unidad') AS unit_name,
           coalesce(nullif(btrim(u.code), ''), '') AS unit_code
    FROM engagement.audits a
    LEFT JOIN engagement.files f ON f.id = a.file_id
    LEFT JOIN engagement.units u ON u.id = f.unit_id
    WHERE a.status <> 'ANULADA'
      AND (CAST(:unit_id AS integer) IS NULL OR f.unit_id = CAST(:unit_id AS integer))
      AND (CAST(:audit_domain AS text) IS NULL OR upper(coalesce(a.audit_domain, '')) = CAST(:audit_domain AS text))
      AND (CAST(:auditor_id AS uuid) IS NULL OR EXISTS (
          SELECT 1 FROM engagement.team t
          WHERE t.audit_id = a.id AND t.user_id = CAST(:auditor_id AS uuid)
      ))
), observation_scope AS (
    SELECT o.id, o.audit_id, o.created_at, o.pac_status,
           s.unit_id, s.unit_name, s.unit_code,
           {RISK_CASE} AS risk_bucket,
           CASE WHEN upper(trim(coalesce(o.pac_status, ''))) IN
             ('CUMPLIDA','CUMPLIDO','CLOSED','CLOSED_RESOLVED','CLOSED_FP','RESUELTO','RESUELTA','CERRADO','CERRADA','CANCELLED','CANCELADA')
             THEN FALSE ELSE TRUE END AS is_open
    FROM engagement.observations o
    JOIN observed_audits s ON s.id = o.audit_id
    WHERE o.created_at >= :start_at AND o.created_at < :end_before
)"""

METRICS: dict[str, dict[str, str]] = {
    "AUDITS_TOTAL": {"label": "Auditorías creadas en el período", "unit": "auditorías", "description": "Auditorías creadas dentro del período seleccionado."},
    "AUDITS_IN_PROGRESS": {"label": "Auditorías en curso", "unit": "auditorías", "description": "Auditorías en estado de ejecución según el estado registrado."},
    "AUDITS_CLOSED": {"label": "Auditorías cerradas de la cohorte", "unit": "auditorías", "description": "De las auditorías creadas en el período, cuántas tienen actualmente un estado de cierre reconocido por SICAS; no equivale necesariamente a cierres realizados dentro del período."},
    "AUDIT_COMPLETION_PCT": {"label": "Porcentaje de cierre de cohorte", "unit": "%", "description": "Porcentaje de auditorías creadas en el período que actualmente están cerradas."},
    "OBSERVATIONS_TOTAL": {"label": "Brechas / observaciones creadas en el período", "unit": "observaciones", "description": "Observaciones cuya propia fecha de creación cae dentro del período, asociadas a las unidades, dominios y auditores seleccionados."},
    "HIGH_RISK_OBSERVATIONS": {"label": "Brechas de riesgo alto o crítico creadas en el período", "unit": "observaciones", "description": "Observaciones de riesgo ALTO/HIGH o CRÍTICO/CRITICAL cuya fecha de creación cae dentro del período."},
    "HIGH_RISK_SHARE_PCT": {"label": "Porcentaje de brechas de riesgo alto o crítico", "unit": "%", "description": "Brechas de riesgo alto o crítico divididas entre todas las observaciones."},
    "AVG_CLOSED_AUDIT_DAYS": {"label": "Días hábiles promedio hasta cierre formal", "unit": "días hábiles", "description": "Promedio desde la creación hasta el envío del PAC (pac_sent_at) en las auditorías cerradas de la cohorte; si falta la fecha de cierre, esa auditoría no se incluye en el promedio."},
    "AVG_PHASE_HOURS": {"label": "Horas hábiles promedio transcurridas por fase", "unit": "horas hábiles", "description": "Duración entre cambios de fase; la fase terminal de una auditoría cerrada termina en el envío del PAC. Las fases actuales no cerradas se miden hasta ahora. No representa tiempo activo del auditor."},
    "INGESTION_AVG_SECONDS": {"label": "Duración promedio de carga de datos", "unit": "segundos", "description": "Promedio entre creación y finalización de las cargas terminadas en el período."},
    "INGESTION_REJECTION_PCT": {"label": "Porcentaje de filas rechazadas en cargas", "unit": "%", "description": "Filas rechazadas divididas entre filas procesadas más rechazadas."},
}

PERIODICITIES = {"MENSUAL", "TRIMESTRAL", "SEMESTRAL", "ANUAL"}
DIRECTIONS = {"AT_LEAST", "AT_MOST"}
SCOPES = {"GENERAL", "UNIDAD", "AUDITOR"}


def _date_arg(value: str | None, fallback: date, label: str) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Fecha {label} inválida; use AAAA-MM-DD.") from exc


def parse_filters(args: Any) -> dict[str, Any]:
    today = date.today()
    start = _date_arg(args.get("start_date"), today - timedelta(days=364), "inicial")
    end = _date_arg(args.get("end_date"), today, "final")
    if start > end:
        raise ValueError("La fecha inicial no puede ser posterior a la fecha final.")
    if (end - start).days > 3660:
        raise ValueError("El rango máximo de consulta es de diez años.")

    unit_raw = args.get("unit_id") or None
    try:
        unit_id = int(unit_raw) if unit_raw else None
        if unit_id is not None and unit_id < 1:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("La unidad seleccionada no es válida.") from exc

    auditor_raw = (args.get("auditor_id") or "").strip() or None
    if auditor_raw:
        try:
            auditor_raw = str(UUID(auditor_raw))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("El auditor seleccionado no es válido.") from exc

    domain = (args.get("audit_domain") or "").strip().upper() or None
    if domain and domain not in {"FINANCIERA", "SISTEMAS", "GENERAL"}:
        raise ValueError("El dominio de auditoría no es válido.")

    granularity = (args.get("granularity") or "MONTH").strip().upper()
    if granularity not in {"MONTH", "QUARTER", "SEMESTER", "YEAR"}:
        raise ValueError("La periodicidad del gráfico no es válida.")

    return {
        "start_date": start,
        "end_date": end,
        "start_at": datetime.combine(start, time.min, tzinfo=timezone.utc),
        "end_before": datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc),
        "unit_id": unit_id,
        "auditor_id": auditor_raw,
        "audit_domain": None if domain == "GENERAL" else domain,
        "granularity": granularity,
    }


def _mappings(statement: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in db.session.execute(text(statement), params).mappings().all()]


def _one(statement: str, params: dict[str, Any]) -> dict[str, Any]:
    row = db.session.execute(text(statement), params).mappings().one()
    return dict(row)


def _period_expression(granularity: str, alias: str = "s", column: str = "created_at") -> str:
    field = f"{alias}.{column}"
    return {
        "MONTH": f"date_trunc('month', {field})",
        "QUARTER": f"date_trunc('quarter', {field})",
        "SEMESTER": f"date_trunc('year', {field}) + CASE WHEN extract(month FROM {field}) > 6 THEN interval '6 months' ELSE interval '0 months' END",
        "YEAR": f"date_trunc('year', {field})",
    }[granularity]


def _period_key(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _empty_unit(unit_id: int | None, unit_code: str, unit_name: str) -> dict[str, Any]:
    return {
        "unit_id": unit_id, "unit_code": unit_code, "unit_name": unit_name,
        "audits_total": 0, "audits_in_progress": 0, "audits_closed": 0,
        "avg_closed_audit_days": None,
        "observations_total": 0, "high_risk_observations": 0, "observations_open": 0,
        "risk_breakdown": {key: 0 for key in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNSPECIFIED", "OTHER")},
    }


def _period_floor(day: date, granularity: str) -> date:
    if granularity == "MONTH":
        return date(day.year, day.month, 1)
    if granularity == "QUARTER":
        return date(day.year, ((day.month - 1) // 3) * 3 + 1, 1)
    if granularity == "SEMESTER":
        return date(day.year, 1 if day.month <= 6 else 7, 1)
    if granularity == "YEAR":
        return date(day.year, 1, 1)
    raise ValueError("La periodicidad del gráfico no es válida.")


def _next_period(day: date, granularity: str) -> date:
    if granularity == "MONTH":
        return date(day.year + (day.month == 12), 1 if day.month == 12 else day.month + 1, 1)
    if granularity == "QUARTER":
        month = day.month + 3
        return date(day.year + (month > 12), month - 12 if month > 12 else month, 1)
    if granularity == "SEMESTER":
        return date(day.year + (day.month == 7), 1 if day.month == 7 else 7, 1)
    if granularity == "YEAR":
        return date(day.year + 1, 1, 1)
    raise ValueError("La periodicidad del gráfico no es válida.")


def _get_domain_comparison(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Compara FINANCIERA y SISTEMAS en paralelo sin aplicar el filtro de dominio.

    Auditorías/avance de ítems se agrupan por fecha de creación de la auditoría;
    observaciones, por su propia fecha de creación. Los contadores se mantienen separados.
    """
    params = {k: filters[k] for k in ("start_at", "end_before", "unit_id", "auditor_id")}
    domain_locked = bool(filters.get("_domain_locked"))
    params.update({"audit_domain": filters.get("audit_domain"), "domain_locked": domain_locked})
    rows = _mappings(f"""
        WITH domain_list AS (
            SELECT 'FINANCIERA'::text AS audit_domain
            UNION ALL SELECT 'SISTEMAS'::text
        ), audit_candidates AS (
            SELECT a.id, upper(coalesce(a.audit_domain, '')) AS audit_domain,
                   a.status, a.created_at, a.pac_sent_at, f.unit_id
            FROM engagement.audits a
            LEFT JOIN engagement.files f ON f.id = a.file_id
            WHERE upper(coalesce(a.audit_domain, '')) IN ('FINANCIERA', 'SISTEMAS') AND a.status <> 'ANULADA'
              AND (NOT :domain_locked OR upper(coalesce(a.audit_domain, '')) = CAST(:audit_domain AS text))
              AND (CAST(:unit_id AS integer) IS NULL OR f.unit_id = CAST(:unit_id AS integer))
              AND (CAST(:auditor_id AS uuid) IS NULL OR EXISTS (
                  SELECT 1 FROM engagement.team t
                  WHERE t.audit_id = a.id AND t.user_id = CAST(:auditor_id AS uuid)
              ))
        ), audit_cohort AS (
            SELECT * FROM audit_candidates
            WHERE created_at >= :start_at AND created_at < :end_before
        ), audit_totals AS (
            SELECT s.audit_domain,
                   count(*)::integer AS audits_total,
                   (count(*) FILTER (WHERE {IN_PROGRESS_SQL}))::integer AS audits_in_progress,
                   (count(*) FILTER (WHERE {CLOSED_SQL}))::integer AS audits_closed,
                   round((avg(CASE
                       WHEN upper(coalesce(s.status, '')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
                         AND s.pac_sent_at IS NOT NULL
                       THEN greatest(engagement.business_seconds(s.created_at, s.pac_sent_at) / 32400.0, 0)
                       ELSE NULL END))::numeric, 2) AS avg_closed_audit_days
            FROM audit_cohort s GROUP BY s.audit_domain
        ), item_totals AS (
            SELECT c.audit_domain,
                   count(i.id)::integer AS items_total,
                   (count(i.id) FILTER (WHERE i.auto_score IS NOT NULL OR i.manual_score IS NOT NULL))::integer AS items_scored
            FROM audit_cohort c
            JOIN engagement.worksheets w ON w.audit_id = c.id
            LEFT JOIN engagement.items i ON i.worksheet_id = w.id
            GROUP BY c.audit_domain
        ), observation_base AS (
            SELECT c.audit_domain, o.id, o.item_id, o.pac_status,
                   {RISK_CASE} AS risk_bucket,
                   CASE WHEN upper(trim(coalesce(o.pac_status, ''))) IN
                     ('CUMPLIDA','CUMPLIDO','CLOSED','CLOSED_RESOLVED','CLOSED_FP','RESUELTO','RESUELTA','CERRADO','CERRADA','CANCELLED','CANCELADA')
                     THEN FALSE ELSE TRUE END AS is_open
            FROM audit_candidates c
            JOIN engagement.observations o ON o.audit_id = c.id
            WHERE o.created_at >= :start_at AND o.created_at < :end_before
        ), observation_totals AS (
            SELECT audit_domain,
                   count(*)::integer AS observations_total,
                   (count(*) FILTER (WHERE is_open))::integer AS observations_open,
                   (count(*) FILTER (WHERE risk_bucket = 'CRITICAL'))::integer AS critical_observations,
                   (count(*) FILTER (WHERE risk_bucket = 'HIGH'))::integer AS high_risk_observations,
                   (count(*) FILTER (WHERE risk_bucket = 'MEDIUM'))::integer AS medium_observations,
                   (count(*) FILTER (WHERE risk_bucket = 'LOW'))::integer AS low_observations,
                   (count(*) FILTER (WHERE risk_bucket = 'UNSPECIFIED'))::integer AS unclassified_observations,
                   (count(*) FILTER (WHERE risk_bucket = 'OTHER'))::integer AS other_observations,
                   (count(*) FILTER (WHERE item_id IS NULL))::integer AS observations_without_item,
                   count(DISTINCT item_id)::integer AS criteria_with_formal_observation
            FROM observation_base GROUP BY audit_domain
        )
        SELECT d.audit_domain,
               coalesce(a.audits_total, 0) AS audits_total,
               coalesce(a.audits_in_progress, 0) AS audits_in_progress,
               coalesce(a.audits_closed, 0) AS audits_closed,
               a.avg_closed_audit_days,
               coalesce(o.observations_total, 0) AS observations_total,
               coalesce(o.observations_open, 0) AS observations_open,
               coalesce(o.critical_observations, 0) AS critical_observations,
               coalesce(o.high_risk_observations, 0) AS high_risk_observations,
               coalesce(o.medium_observations, 0) AS medium_observations,
               coalesce(o.low_observations, 0) AS low_observations,
               coalesce(o.unclassified_observations, 0) AS unclassified_observations,
               coalesce(o.other_observations, 0) AS other_observations,
               coalesce(o.observations_without_item, 0) AS observations_without_item,
               coalesce(o.criteria_with_formal_observation, 0) AS criteria_with_formal_observation,
               coalesce(i.items_total, 0) AS items_total,
               coalesce(i.items_scored, 0) AS items_scored
        FROM domain_list d
        LEFT JOIN audit_totals a ON a.audit_domain = d.audit_domain
        LEFT JOIN item_totals i ON i.audit_domain = d.audit_domain
        LEFT JOIN observation_totals o ON o.audit_domain = d.audit_domain
        ORDER BY CASE d.audit_domain WHEN 'FINANCIERA' THEN 1 ELSE 2 END
    """, params)
    for row in rows:
        row["items_scored_pct"] = _safe_pct(row["items_scored"], row["items_total"])
        row["high_risk_pct"] = _safe_pct(
            row["critical_observations"] + row["high_risk_observations"], row["observations_total"]
        )
    if domain_locked:
        rows = [row for row in rows if row["audit_domain"] == filters["audit_domain"]]
    return rows

# El centro de control muestra estado actual; no queda recortado por la cohorte histórica.
CURRENT_SCOPE_CTE = """WITH current_audit_scope AS (
    SELECT a.id, a.code, a.status, a.phase, upper(coalesce(a.audit_domain, 'SIN_DOMINIO')) AS audit_domain,
           a.created_at, a.planned_start, a.planned_end, a.pac_sent_at, f.unit_id,
           coalesce(nullif(btrim(u.name), ''), 'Sin unidad') AS unit_name,
           coalesce(nullif(btrim(u.code), ''), '') AS unit_code
    FROM engagement.audits a
    LEFT JOIN engagement.files f ON f.id = a.file_id
    LEFT JOIN engagement.units u ON u.id = f.unit_id
    WHERE a.status <> 'ANULADA'
      AND (CAST(:unit_id AS integer) IS NULL OR f.unit_id = CAST(:unit_id AS integer))
      AND (CAST(:audit_domain AS text) IS NULL OR CAST(:audit_domain AS text) = 'GENERAL'
           OR upper(coalesce(a.audit_domain, '')) = CAST(:audit_domain AS text))
      AND (CAST(:auditor_id AS uuid) IS NULL OR EXISTS (
          SELECT 1 FROM engagement.team t
          WHERE t.audit_id = a.id AND t.user_id = CAST(:auditor_id AS uuid)
      ))
)"""


def _current_scope_params(filters: dict[str, Any]) -> dict[str, Any]:
    domain = filters.get("audit_domain")
    return {
        "unit_id": filters.get("unit_id"),
        "auditor_id": filters.get("auditor_id"),
        "audit_domain": None if domain in (None, "", "GENERAL") else domain,
    }


def get_control_alerts(filters: dict[str, Any], limit: int = 250) -> list[dict[str, Any]]:
    """Alertas de estado actual; solo agrega metadatos de expediente y compromisos."""
    limit = max(1, min(int(limit), 250))
    params = _current_scope_params(filters)
    return _mappings(CURRENT_SCOPE_CTE + """, latest_activity AS (
        SELECT s.*, coalesce(lp.last_changed_at, s.created_at) AS last_activity_at
        FROM current_audit_scope s
        LEFT JOIN LATERAL (
            SELECT max(pl.changed_at) AS last_changed_at
            FROM engagement.phase_log pl WHERE pl.audit_id = s.id
        ) lp ON TRUE
    ), alerts AS (
        SELECT 'AUDITORIA_VENCIDA'::text AS alert_type, 'ALTA'::text AS severity,
               a.code::text AS audit_code, a.audit_domain::text AS domain, a.unit_name::text AS unit_name,
               'La fecha prevista de finalización ya venció'::text AS detail,
               a.planned_end::date AS due_date,
               greatest(CURRENT_DATE - a.planned_end, 0)::integer AS days_overdue,
               coalesce(a.phase, 'SIN_FASE')::text AS phase
        FROM latest_activity a
        WHERE upper(coalesce(a.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
          AND a.planned_end IS NOT NULL AND a.planned_end < CURRENT_DATE
        UNION ALL
        SELECT 'FASE_SIN_MOVIMIENTO', 'MEDIA', a.code::text, a.audit_domain::text, a.unit_name::text,
               'Sin cambios de fase registrados por 14 días o más', NULL::date,
               greatest(CURRENT_DATE - a.last_activity_at::date, 0)::integer, coalesce(a.phase,'SIN_FASE')::text
        FROM latest_activity a
        WHERE upper(coalesce(a.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
          AND a.last_activity_at < CURRENT_TIMESTAMP - interval '14 days'
        UNION ALL
        SELECT 'SIN_RESPONSABLE', 'MEDIA', a.code::text, a.audit_domain::text, a.unit_name::text,
               'Auditoría sin integrante asignado en el equipo', NULL::date,
               greatest(CURRENT_DATE - a.created_at::date, 0)::integer, coalesce(a.phase,'SIN_FASE')::text
        FROM latest_activity a
        WHERE upper(coalesce(a.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
          AND NOT EXISTS (SELECT 1 FROM engagement.team t WHERE t.audit_id = a.id)
        UNION ALL
        SELECT 'CIERRE_SIN_FECHA', 'MEDIA', a.code::text, a.audit_domain::text, a.unit_name::text,
               'El expediente figura cerrado pero no tiene fecha de envío del PAC', NULL::date,
               greatest(CURRENT_DATE - a.created_at::date, 0)::integer, coalesce(a.phase,'SIN_FASE')::text
        FROM latest_activity a
        WHERE upper(coalesce(a.status,'')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
          AND a.pac_sent_at IS NULL
        UNION ALL
        SELECT 'INFORME_PENDIENTE',
               CASE WHEN r.submitted_at IS NOT NULL AND r.submitted_at < CURRENT_TIMESTAMP - interval '7 days' THEN 'ALTA' ELSE 'MEDIA' END,
               a.code::text, a.audit_domain::text, a.unit_name::text,
               ('Informe pendiente de aprobación (' || coalesce(nullif(r.status,''),'SIN_ESTADO') || ')')::text,
               NULL::date, greatest(CURRENT_DATE - coalesce(r.submitted_at, a.created_at)::date, 0)::integer,
               coalesce(a.phase,'SIN_FASE')::text
        FROM latest_activity a JOIN engagement.reports r ON r.audit_id = a.id
        WHERE upper(coalesce(r.status,'')) IN ('IN_REVIEW','GERENCIA','CONTRALOR','SUBMITTED','PENDING')
        UNION ALL
        SELECT 'PAC_VENCIDO', 'ALTA', a.code::text, a.audit_domain::text, a.unit_name::text,
               ('Compromiso PAC vencido' || CASE WHEN nullif(trim(coalesce(o.pac_owner,'')), '') IS NOT NULL THEN ' — responsable: ' || trim(o.pac_owner) ELSE '' END)::text,
               o.pac_due::date, greatest(CURRENT_DATE - o.pac_due, 0)::integer, coalesce(a.phase,'SIN_FASE')::text
        FROM latest_activity a JOIN engagement.observations o ON o.audit_id = a.id
        WHERE o.pac_due IS NOT NULL AND o.pac_due < CURRENT_DATE
          AND upper(trim(coalesce(o.pac_status,''))) NOT IN ('CUMPLIDA','CUMPLIDO','CLOSED','CLOSED_RESOLVED','CLOSED_FP','RESUELTO','RESUELTA','CERRADO','CERRADA','CANCELLED','CANCELADA')
        UNION ALL
        SELECT 'BRECHA_ALTO_CRITICA',
               CASE WHEN upper(trim(coalesce(o.risk,''))) IN ('CRITICAL','CRITICO','CRÍTICO','CRITICA','CRÍTICA') THEN 'CRITICA' ELSE 'ALTA' END,
               a.code::text, a.audit_domain::text, a.unit_name::text,
               ('Brecha abierta de riesgo ' || upper(coalesce(o.risk,'SIN_RIESGO')) || ': ' || coalesce(nullif(trim(o.title),''),'sin título'))::text,
               o.pac_due::date, greatest(CURRENT_DATE - o.created_at::date, 0)::integer, coalesce(a.phase,'SIN_FASE')::text
        FROM latest_activity a JOIN engagement.observations o ON o.audit_id = a.id
        WHERE upper(trim(coalesce(o.risk,''))) IN ('HIGH','ALTO','ALTA','CRITICAL','CRITICO','CRÍTICO','CRITICA','CRÍTICA')
          AND upper(trim(coalesce(o.pac_status,''))) NOT IN ('CUMPLIDA','CUMPLIDO','CLOSED','CLOSED_RESOLVED','CLOSED_FP','RESUELTO','RESUELTA','CERRADO','CERRADA','CANCELLED','CANCELADA')
    )
    SELECT alert_type, severity, audit_code, domain, unit_name, detail,
           due_date::text AS due_date, days_overdue, phase
    FROM alerts
    ORDER BY CASE severity WHEN 'CRITICA' THEN 1 WHEN 'ALTA' THEN 2 WHEN 'MEDIA' THEN 3 ELSE 4 END,
             days_overdue DESC, audit_code
    LIMIT """ + str(limit), params)


def get_data_quality(filters: dict[str, Any]) -> dict[str, Any]:
    """Validaciones agregadas. Observaciones generales son informativas, no errores."""
    params = _current_scope_params(filters)
    counts = _one(CURRENT_SCOPE_CTE + """, worksheet_counts AS (
        SELECT w.id, s.id AS audit_id,
               CASE
                 WHEN fw.worksheet_id IS NOT NULL AND jsonb_typeof(fw.criteria_snapshot) = 'array'
                   THEN jsonb_array_length(fw.criteria_snapshot)
                 WHEN jsonb_typeof(w.criteria) = 'array' THEN jsonb_array_length(w.criteria)
                 ELSE 0
               END AS criteria_count,
               count(i.id)::integer AS item_count
        FROM current_audit_scope s JOIN engagement.worksheets w ON w.audit_id = s.id
        LEFT JOIN engagement.financial_worksheets fw ON fw.worksheet_id = w.id
        LEFT JOIN engagement.items i ON i.worksheet_id = w.id
        GROUP BY w.id, s.id, w.criteria, fw.worksheet_id, fw.criteria_snapshot
    )
    SELECT
      (SELECT count(*)::integer FROM current_audit_scope s
       WHERE upper(coalesce(s.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
         AND NOT EXISTS (SELECT 1 FROM engagement.team t WHERE t.audit_id=s.id)) AS audits_without_team,
      (SELECT count(*)::integer FROM current_audit_scope s
       WHERE upper(coalesce(s.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
         AND NOT EXISTS (SELECT 1 FROM engagement.worksheets w WHERE w.audit_id=s.id)) AS open_audits_without_worksheet,
      (SELECT count(*)::integer FROM current_audit_scope s
       WHERE upper(coalesce(s.status,'')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA') AND s.pac_sent_at IS NULL) AS closed_missing_close_date,
      (SELECT count(*)::integer FROM worksheet_counts WHERE criteria_count <> item_count) AS worksheets_item_mismatch,
      (SELECT count(i.id)::integer FROM current_audit_scope s
       JOIN engagement.worksheets w ON w.audit_id=s.id JOIN engagement.items i ON i.worksheet_id=w.id
       WHERE upper(coalesce(s.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
         AND i.auto_score IS NULL AND i.manual_score IS NULL) AS items_without_score,
      (SELECT count(*)::integer FROM current_audit_scope s
       JOIN engagement.observations o ON o.audit_id=s.id
       JOIN engagement.items i ON i.id=o.item_id
       JOIN engagement.worksheets w ON w.id=i.worksheet_id
       WHERE w.audit_id <> o.audit_id) AS cross_audit_observation_links,
      (SELECT count(*)::integer FROM current_audit_scope s
       JOIN engagement.observations o ON o.audit_id=s.id WHERE o.item_id IS NULL) AS general_observations
    """, params)
    checks = [
        {"code": "AUDITS_WITHOUT_TEAM", "label": "Auditorías abiertas sin responsable", "count": counts["audits_without_team"], "level": "ALERTA", "description": "Auditorías abiertas sin integrantes registrados en el equipo."},
        {"code": "OPEN_AUDITS_WITHOUT_WORKSHEET", "label": "Auditorías abiertas sin cédulas", "count": counts["open_audits_without_worksheet"], "level": "ALERTA", "description": "Auditorías abiertas que no tienen cédulas relacionadas."},
        {"code": "CLOSED_MISSING_CLOSE_DATE", "label": "Cierres sin fecha verificable", "count": counts["closed_missing_close_date"], "level": "ALERTA", "description": "Auditorías cerradas sin pac_sent_at; no se calcula una duración de cierre ficticia."},
        {"code": "WORKSHEET_ITEM_MISMATCH", "label": "Cédulas con diferencia criterios/ítems", "count": counts["worksheets_item_mismatch"], "level": "ALERTA", "description": "La cantidad de criterios de la cédula difiere de los ítems operativos asociados."},
        {"code": "CROSS_AUDIT_OBSERVATION_LINK", "label": "Observaciones ligadas a otra auditoría", "count": counts["cross_audit_observation_links"], "level": "ALERTA", "description": "Vínculos de observación e ítem que cruzan expedientes distintos."},
        {"code": "ITEMS_WITHOUT_SCORE", "label": "Ítems sin calificación registrada", "count": counts["items_without_score"], "level": "INFO", "description": "Es una señal de cobertura pendiente, no necesariamente un error: pueden existir excepciones válidas."},
        {"code": "GENERAL_OBSERVATIONS", "label": "Observaciones generales sin ítem", "count": counts["general_observations"], "level": "INFO", "description": "Válidas en SICAS; se muestran aparte y no se cuentan como error de integridad."},
    ]
    return {"issues_total": sum(c["count"] for c in checks if c["level"] == "ALERTA"), "checks": checks}


def get_workflow_pipeline(filters: dict[str, Any]) -> dict[str, Any]:
    """Estado actual por fase e informes; no usa la cohorte histórica."""
    params = _current_scope_params(filters)
    phases = _mappings(CURRENT_SCOPE_CTE + """, current_phase AS (
        SELECT s.id, coalesce(nullif(trim(s.phase),''),'SIN_FASE') AS phase, s.status, s.planned_end,
               coalesce(lp.changed_at, s.created_at) AS entered_at
        FROM current_audit_scope s
        LEFT JOIN LATERAL (SELECT max(pl.changed_at) AS changed_at FROM engagement.phase_log pl WHERE pl.audit_id=s.id) lp ON TRUE
        WHERE upper(coalesce(s.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
    ), phase_list AS (
        SELECT 'PLANIFICACION'::text AS phase UNION ALL SELECT 'TRABAJO_CAMPO' UNION ALL SELECT 'LEVANTAMIENTO'
        UNION ALL SELECT 'DOCUMENTACION' UNION ALL SELECT 'PRUEBAS_CAMPO' UNION ALL SELECT 'INFORME' UNION ALL SELECT 'SIN_FASE'
    )
    SELECT p.phase, count(c.id)::integer AS audits,
           count(c.id) FILTER (WHERE c.planned_end IS NOT NULL AND c.planned_end < CURRENT_DATE)::integer AS overdue,
           round(avg(greatest(engagement.business_seconds(c.entered_at, CURRENT_TIMESTAMP)/3600.0,0))::numeric,2) AS average_phase_hours
    FROM phase_list p LEFT JOIN current_phase c ON upper(c.phase)=upper(p.phase)
    GROUP BY p.phase ORDER BY CASE p.phase WHEN 'PLANIFICACION' THEN 1 WHEN 'TRABAJO_CAMPO' THEN 2 WHEN 'LEVANTAMIENTO' THEN 3
        WHEN 'DOCUMENTACION' THEN 4 WHEN 'PRUEBAS_CAMPO' THEN 5 WHEN 'INFORME' THEN 6 ELSE 7 END
    """, params)
    report_statuses = _mappings(CURRENT_SCOPE_CTE + """
        SELECT coalesce(nullif(trim(r.status),''),'SIN_ESTADO') AS status,
               count(DISTINCT r.id)::integer AS reports
        FROM engagement.reports r JOIN current_audit_scope s ON s.id=r.audit_id
        WHERE upper(coalesce(r.status,'')) IN ('IN_REVIEW','GERENCIA','CONTRALOR','SUBMITTED','PENDING')
        GROUP BY 1 ORDER BY 1
    """, params)
    return {"phases": phases, "pending_reports": report_statuses}


def get_auditor_workload(filters: dict[str, Any]) -> list[dict[str, Any]]:
    """Carga asignada y horas activas declaradas mediante el cronómetro SICAS."""
    rows = _mappings(CURRENT_SCOPE_CTE + """, active_audits AS (
        SELECT s.*,
               (SELECT count(*)::integer FROM engagement.observations o
                WHERE o.audit_id=s.id
                  AND upper(trim(coalesce(o.risk,''))) IN ('HIGH','ALTO','ALTA','CRITICAL','CRITICO','CRÍTICO','CRITICA','CRÍTICA')
                  AND upper(trim(coalesce(o.pac_status,''))) NOT IN ('CUMPLIDA','CUMPLIDO','CLOSED','CLOSED_RESOLVED','CLOSED_FP','RESUELTO','RESUELTA','CERRADO','CERRADA','CANCELLED','CANCELADA')) AS open_high_risk
        FROM current_audit_scope s
        WHERE upper(coalesce(s.status,'')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
    ), auditor_active AS (
        SELECT DISTINCT u.id AS auditor_id, coalesce(nullif(u.full_name,''),u.username) AS auditor_name,
               a.id AS audit_id, a.planned_end, a.created_at, a.open_high_risk
        FROM active_audits a JOIN engagement.team t ON t.audit_id=a.id
        JOIN iam.users u ON u.id=t.user_id
    )
    SELECT auditor_id::text AS auditor_id, auditor_name,
           count(DISTINCT audit_id)::integer AS active_audits,
           count(DISTINCT audit_id) FILTER (WHERE planned_end IS NOT NULL AND planned_end < CURRENT_DATE)::integer AS overdue_audits,
           coalesce(sum(open_high_risk),0)::integer AS open_high_risk,
           round((avg(greatest(engagement.business_seconds(created_at, CURRENT_TIMESTAMP)/32400.0,0)))::numeric,2) AS average_open_age_days
    FROM auditor_active
    GROUP BY auditor_id, auditor_name
    ORDER BY active_audits DESC, overdue_audits DESC, auditor_name
    """, _current_scope_params(filters))

    activity_params = {
        **_current_scope_params(filters),
        "start_at": filters["start_at"],
        "end_before": filters["end_before"],
    }
    activity_rows = _mappings(CURRENT_SCOPE_CTE + """, tracked AS (
        SELECT x.user_id,
               sum(x.accumulated_seconds + CASE WHEN x.status='RUNNING' AND x.last_resumed_at IS NOT NULL
                   THEN greatest(engagement.business_seconds(x.last_resumed_at, CURRENT_TIMESTAMP),0)::bigint
                   ELSE 0 END)::bigint AS active_seconds,
               count(*)::integer AS sessions
        FROM analytics.auditor_activity_sessions x
        JOIN current_audit_scope s ON s.id=x.audit_id
        WHERE x.started_at >= :start_at AND x.started_at < :end_before
        GROUP BY x.user_id
    )
    SELECT u.id::text AS auditor_id,
           round((t.active_seconds / 3600.0)::numeric, 2) AS tracked_active_hours,
           t.sessions AS tracked_sessions
    FROM tracked t JOIN iam.users u ON u.id=t.user_id
    """, activity_params)
    by_id = {row["auditor_id"]: row for row in rows}
    for activity in activity_rows:
        target = by_id.get(activity["auditor_id"])
        if target is None:
            target = {
                "auditor_id": activity["auditor_id"], "auditor_name": activity.get("auditor_name", "Auditor"),
                "active_audits": 0, "overdue_audits": 0, "open_high_risk": 0,
                "average_open_age_days": None,
            }
            # Use the canonical display name supplied by the users table.
            user_name = db.session.execute(text("SELECT coalesce(nullif(full_name,''),username) FROM iam.users WHERE id=CAST(:id AS uuid)"),
                                           {"id": activity["auditor_id"]}).scalar_one_or_none()
            target["auditor_name"] = user_name or "Auditor"
            rows.append(target)
            by_id[activity["auditor_id"]] = target
        target["tracked_active_hours"] = activity["tracked_active_hours"]
        target["tracked_sessions"] = activity["tracked_sessions"]
    for target in rows:
        target.setdefault("tracked_active_hours", 0.0)
        target.setdefault("tracked_sessions", 0)
    return sorted(rows, key=lambda row: (-row["active_audits"], -row["tracked_active_hours"], row["auditor_name"]))


def get_activity_options(user_id: str) -> dict[str, Any]:
    """Devuelve expedientes asignados disponibles, sesión vigente e historial reciente propio."""
    user = str(UUID(str(user_id)))
    audits = _mappings("""
        SELECT a.id::text AS audit_id, a.code, upper(coalesce(a.audit_domain,'')) AS audit_domain,
               coalesce(nullif(trim(u.name),''),'Sin unidad') AS unit_name,
               coalesce(nullif(trim(a.phase),''),'SIN_FASE') AS phase, a.planned_end::text AS planned_end
        FROM engagement.audits a
        LEFT JOIN engagement.files f ON f.id=a.file_id
        LEFT JOIN engagement.units u ON u.id=f.unit_id
        JOIN engagement.team t ON t.audit_id=a.id AND t.user_id=CAST(:user_id AS uuid)
        WHERE upper(coalesce(a.status,'')) IN ('IN_PROGRESS','IN PROGRESS','EN_CURSO','EN CURSO','RUNNING')
          AND upper(coalesce(a.phase,'')) IN ('TRABAJO_CAMPO','INFORME','LEVANTAMIENTO','DOCUMENTACION','PRUEBAS_CAMPO')
        ORDER BY a.planned_end NULLS LAST, a.created_at, a.code
    """, {"user_id": user})
    current = get_current_activity_session(user)
    recent = _mappings("""
        SELECT x.id::text AS id, x.audit_id::text AS audit_id, a.code AS audit_code,
               x.started_at, x.ended_at, x.status, x.accumulated_seconds::bigint AS accumulated_seconds,
               (x.accumulated_seconds + CASE WHEN x.status='RUNNING' AND x.last_resumed_at IS NOT NULL
                   THEN greatest(engagement.business_seconds(x.last_resumed_at, CURRENT_TIMESTAMP),0)::bigint
                   ELSE 0 END)::bigint AS elapsed_seconds
        FROM analytics.auditor_activity_sessions x
        JOIN engagement.audits a ON a.id=x.audit_id
        WHERE x.user_id=CAST(:user_id AS uuid)
        ORDER BY x.started_at DESC LIMIT 10
    """, {"user_id": user})
    for row in recent:
        for key in ("started_at", "ended_at"):
            if row.get(key) is not None: row[key] = row[key].isoformat()
    return {"audits": audits, "current": current, "recent_sessions": recent}


def get_current_activity_session(user_id: str) -> dict[str, Any] | None:
    user = str(UUID(str(user_id)))
    row = db.session.execute(text("""
        SELECT x.id::text AS id, x.audit_id::text AS audit_id, a.code AS audit_code,
               upper(coalesce(a.audit_domain,'')) AS audit_domain,
               coalesce(nullif(trim(u.name),''),'Sin unidad') AS unit_name,
               coalesce(nullif(trim(a.phase),''),'SIN_FASE') AS phase,
               x.started_at, x.last_resumed_at, x.status,
               (x.accumulated_seconds + CASE WHEN x.status='RUNNING' AND x.last_resumed_at IS NOT NULL
                    THEN greatest(engagement.business_seconds(x.last_resumed_at, CURRENT_TIMESTAMP),0)::bigint ELSE 0 END)::bigint AS elapsed_seconds,
               x.accumulated_seconds::bigint AS accumulated_seconds
        FROM analytics.auditor_activity_sessions x
        JOIN engagement.audits a ON a.id=x.audit_id
        LEFT JOIN engagement.files f ON f.id=a.file_id
        LEFT JOIN engagement.units u ON u.id=f.unit_id
        WHERE x.user_id=CAST(:user_id AS uuid) AND x.status IN ('RUNNING','PAUSED')
        ORDER BY x.started_at DESC LIMIT 1
    """), {"user_id": user}).mappings().first()
    if not row: return None
    out = dict(row)
    for key in ("started_at", "last_resumed_at"):
        if out.get(key) is not None: out[key] = out[key].isoformat()
    out["elapsed_seconds"] = int(out["elapsed_seconds"] or 0)
    out["accumulated_seconds"] = int(out["accumulated_seconds"] or 0)
    return out


def start_activity_session(audit_id: str, user_id: str) -> dict[str, Any]:
    user = str(UUID(str(user_id))); audit = str(UUID(str(audit_id)))
    eligible = db.session.execute(text("""
        SELECT a.id::text AS audit_id, a.code, a.phase
        FROM engagement.audits a
        JOIN engagement.team t ON t.audit_id=a.id
        WHERE a.id=CAST(:audit_id AS uuid) AND t.user_id=CAST(:user_id AS uuid)
          AND upper(coalesce(a.status,'')) IN ('IN_PROGRESS','IN PROGRESS','EN_CURSO','EN CURSO','RUNNING')
          AND upper(coalesce(a.phase,'')) IN ('TRABAJO_CAMPO','INFORME','LEVANTAMIENTO','DOCUMENTACION','PRUEBAS_CAMPO')
        LIMIT 1
    """), {"audit_id": audit, "user_id": user}).mappings().first()
    if not eligible:
        raise ValueError("Solo puedes iniciar actividad en una auditoría asignada, en curso y en Trabajo de campo o Informe.")
    active = db.session.execute(text("""
        SELECT id::text AS id, audit_id::text AS audit_id, status
        FROM analytics.auditor_activity_sessions
        WHERE user_id=CAST(:user_id AS uuid) AND status IN ('RUNNING','PAUSED')
        ORDER BY started_at DESC LIMIT 1 FOR UPDATE
    """), {"user_id": user}).mappings().first()
    if active:
        raise ValueError("Ya tienes una sesión de actividad iniciada o pausada. Reanúdala o finalízala antes de iniciar otra.")
    result = db.session.execute(text("""
        INSERT INTO analytics.auditor_activity_sessions
          (audit_id,user_id,status,started_at,last_resumed_at,accumulated_seconds)
        VALUES (CAST(:audit_id AS uuid),CAST(:user_id AS uuid),'RUNNING',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)
        RETURNING id::text AS id
    """), {"audit_id": audit, "user_id": user}).mappings().one()
    db.session.commit()
    _write_activity_audit("AUDITOR_ACTIVITY_STARTED", result["id"], user, audit,
                          {"audit_code": eligible["code"], "phase": eligible["phase"]})
    return get_current_activity_session(user) or {"id": result["id"], "status": "RUNNING"}


def transition_activity_session(action: str, user_id: str) -> dict[str, Any]:
    user = str(UUID(str(user_id))); action = str(action).strip().upper()
    if action not in {"PAUSE", "RESUME", "STOP"}:
        raise ValueError("Acción de actividad no válida.")
    current = db.session.execute(text("""
        SELECT id::text AS id, audit_id::text AS audit_id, status, last_resumed_at,
               accumulated_seconds::bigint AS accumulated_seconds
        FROM analytics.auditor_activity_sessions
        WHERE user_id=CAST(:user_id AS uuid) AND status IN ('RUNNING','PAUSED')
        ORDER BY started_at DESC LIMIT 1 FOR UPDATE
    """), {"user_id": user}).mappings().first()
    if not current:
        raise LookupError("No tienes una sesión de actividad activa.")
    state = current["status"]
    if action == "PAUSE" and state != "RUNNING": raise ValueError("Solo se puede pausar una sesión en ejecución.")
    if action == "RESUME" and state != "PAUSED": raise ValueError("Solo se puede reanudar una sesión pausada.")
    if action == "PAUSE":
        db.session.execute(text("""
            UPDATE analytics.auditor_activity_sessions
            SET accumulated_seconds=accumulated_seconds+greatest(engagement.business_seconds(last_resumed_at, CURRENT_TIMESTAMP),0)::bigint,
                status='PAUSED',last_resumed_at=NULL,updated_at=CURRENT_TIMESTAMP
            WHERE id=CAST(:id AS uuid)
        """), {"id": current["id"]})
    elif action == "RESUME":
        db.session.execute(text("""
            UPDATE analytics.auditor_activity_sessions
            SET status='RUNNING',last_resumed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            WHERE id=CAST(:id AS uuid)
        """), {"id": current["id"]})
    else:
        db.session.execute(text("""
            UPDATE analytics.auditor_activity_sessions
            SET accumulated_seconds=accumulated_seconds+CASE WHEN status='RUNNING' AND last_resumed_at IS NOT NULL
                    THEN greatest(engagement.business_seconds(last_resumed_at, CURRENT_TIMESTAMP),0)::bigint ELSE 0 END,
                status='STOPPED',last_resumed_at=NULL,ended_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            WHERE id=CAST(:id AS uuid)
        """), {"id": current["id"]})
    db.session.commit()
    _write_activity_audit("AUDITOR_ACTIVITY_" + action, current["id"], user, current["audit_id"],
                          {"previous_status": state})
    return get_current_activity_session(user) or {"id": current["id"], "status": "STOPPED" if action == "STOP" else action}


def _write_activity_audit(action: str, session_id: str, user_id: str, audit_id: str, details: dict[str, Any]) -> None:
    """Registra los cambios de cronómetro después de confirmar la transición de sesión."""
    try:
        from app.core.audit.audit_service import audit as audit_event
        from flask import g, has_request_context
        audit_event(action=action, outcome="SUCCESS", entity_type="auditor_activity_session",
                    entity_id=session_id, after_data={"audit_id": audit_id, "user_id": user_id, **details},
                    metadata={"component": "sicas_activity_tracker", "event_version": 1},
                    request_id=getattr(g, "request_id", None) if has_request_context() else None)
    except Exception:  # noqa: BLE001 - el registro horario ya quedó confirmado
        import logging
        logging.getLogger("audit").exception("No se pudo registrar el evento de actividad %s", action)


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def create_dashboard_snapshot(filters: dict[str, Any], actor_id: str | None = None, source: str = "MANUAL") -> dict[str, Any]:
    """Guarda un corte inmutable agregado y las mediciones KPI de ese momento."""
    source = str(source or "MANUAL").upper()
    if source not in {"MANUAL", "AUTOMATICO"}:
        raise ValueError("Tipo de corte no válido.")
    data = get_dashboard_data(filters)
    kpis = list_kpis(as_of=filters["end_date"])
    snapshot_data = _json_safe({
        "filters": data["filters"], "summary": data["summary"], "by_domain": data["by_domain"],
        "risk_summary": data["observations_by_risk"], "alert_summary": data["alert_summary"],
        "data_quality": {"issues_total": data["data_quality"]["issues_total"]},
        "phase_pipeline": data["phase_pipeline"]["phases"], "workload": data["workload"],
        "kpis": [{"id": k["id"], "name": k["name"], "metric_code": k["metric_code"],
                  "actual_value": k["actual_value"], "target_value": k["target_value"],
                  "warning_value": k["warning_value"], "status_result": k["status_result"],
                  "period_start": k["period_start"], "period_end": k["period_end"]} for k in kpis],
    })
    filters_json = json.dumps(_json_safe(data["filters"]), ensure_ascii=False)
    data_json = json.dumps(snapshot_data, ensure_ascii=False)
    row = db.session.execute(text("""
        INSERT INTO analytics.dashboard_snapshots (source, captured_by, filters, data)
        VALUES (:source, CAST(:actor AS uuid), CAST(:filters AS jsonb), CAST(:data AS jsonb))
        RETURNING id::text AS id, snapshot_date::text AS snapshot_date, created_at
    """), {"source": source, "actor": str(UUID(actor_id)) if actor_id else None,
           "filters": filters_json, "data": data_json}).mappings().one()
    for kpi in kpis:
        db.session.execute(text("""
            INSERT INTO analytics.kpi_measurements
              (snapshot_id, kpi_id, metric_code, actual_value, target_value, warning_value, direction,
               status_result, period_start, period_end)
            VALUES (CAST(:snapshot_id AS uuid), CAST(:kpi_id AS uuid), :metric_code, :actual, :target,
                    :warning, :direction, :status, CAST(:period_start AS date), CAST(:period_end AS date))
            ON CONFLICT (snapshot_id, kpi_id) DO NOTHING
        """), {"snapshot_id": row["id"], "kpi_id": kpi["id"], "metric_code": kpi["metric_code"],
               "actual": kpi["actual_value"], "target": kpi["target_value"], "warning": kpi["warning_value"],
               "direction": kpi["direction"], "status": kpi["status_result"],
               "period_start": kpi["period_start"], "period_end": kpi["period_end"]})
    db.session.commit()
    try:
        from app.core.audit.audit_service import audit as audit_event
        from flask import g, has_request_context
        audit_event(action="CONTRALOR_DASHBOARD_SNAPSHOT_CREATED", outcome="SUCCESS",
                    entity_type="dashboard_snapshot", entity_id=row["id"],
                    after_data={"snapshot_date": row["snapshot_date"], "source": source,
                                "audits_total": snapshot_data["summary"]["audits_total"],
                                "alerts_total": snapshot_data["alert_summary"]["total"]},
                    metadata={"component": "dashboard_contralor", "filters": snapshot_data["filters"]},
                    request_id=getattr(g, "request_id", None) if has_request_context() else None)
    except Exception:  # noqa: BLE001 - el corte ya está confirmado
        import logging
        logging.getLogger("audit").exception("No se pudo registrar el corte histórico del dashboard")
    return {"id": row["id"], "snapshot_date": row["snapshot_date"], "created_at": row["created_at"].isoformat(), "source": source,
            "summary": snapshot_data["summary"], "by_domain": snapshot_data["by_domain"], "kpi_count": len(kpis)}


def list_dashboard_snapshots(limit: int = 12) -> list[dict[str, Any]]:
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("El límite de cortes no es válido.") from exc
    if not 1 <= limit <= 50:
        raise ValueError("Se permiten entre 1 y 50 cortes históricos.")
    rows = _mappings("""
        SELECT s.id::text AS id, s.snapshot_date::text AS snapshot_date, s.created_at,
               s.source, s.filters, s.data->'summary' AS summary,
               s.data->'by_domain' AS by_domain, s.data->'data_quality' AS data_quality,
               count(m.id)::integer AS kpi_count
        FROM analytics.dashboard_snapshots s
        LEFT JOIN analytics.kpi_measurements m ON m.snapshot_id=s.id
        GROUP BY s.id
        ORDER BY s.created_at DESC LIMIT :limit
    """, {"limit": limit})
    for row in rows:
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
    return rows


def get_kpi_measurement_history(kpi_id: str, limit: int = 24) -> list[dict[str, Any]]:
    try:
        normalized = str(UUID(str(kpi_id)))
        limit = int(limit)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("Identificador o límite de historial no válido.") from exc
    if not 1 <= limit <= 60:
        raise ValueError("Se permiten entre 1 y 60 mediciones históricas.")
    rows = _mappings("""
        SELECT s.snapshot_date::text AS snapshot_date, s.created_at,
               m.actual_value, m.target_value, m.warning_value, m.direction,
               m.status_result, m.period_start::text AS period_start, m.period_end::text AS period_end
        FROM analytics.kpi_measurements m
        JOIN analytics.dashboard_snapshots s ON s.id=m.snapshot_id
        WHERE m.kpi_id=CAST(:kpi_id AS uuid)
        ORDER BY s.created_at DESC LIMIT :limit
    """, {"kpi_id": normalized, "limit": limit})
    for row in rows:
        if row.get("created_at") is not None:
            row["created_at"] = row["created_at"].isoformat()
        for key in ("actual_value", "target_value", "warning_value"):
            if row.get(key) is not None:
                row[key] = float(row[key])
    return rows


def _report_table(headers: list[str], rows: list[list[Any]]) -> str:
    th = "".join(f"<th>{html.escape(str(x))}</th>" for x in headers)
    tr = []
    for row in rows:
        cells = "".join(f"<td>{html.escape('—' if v is None else str(v))}</td>" for v in row)
        tr.append(f"<tr>{cells}</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{th}</tr></thead><tbody>{''.join(tr) or '<tr><td colspan=\"99\">Sin registros para los filtros.</td></tr>'}</tbody></table></div>"


def export_pdf_report(data: dict[str, Any], kpis: list[dict[str, Any]]) -> BytesIO:
    """Genera un PDF real; reportlab se instala como dependencia de la aplicación."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
    from xml.sax.saxutils import escape

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm,
                            topMargin=14*mm, bottomMargin=14*mm, title="Informe ejecutivo de Contraloría — SICAS",
                            author="SICAS")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SicasSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7,
                              leading=8.5, spaceAfter=0, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="SicasSection", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12,
                              leading=14, textColor=colors.HexColor("#17365D"), spaceBefore=10, spaceAfter=5))
    styles.add(ParagraphStyle(name="SicasTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=19,
                              leading=22, textColor=colors.HexColor("#17365D"), spaceAfter=7))

    def cell(value):
        raw = "—" if value is None else str(value)
        return Paragraph(escape(raw).replace("\n", "<br/>"), styles["SicasSmall"])

    def table(headers, rows, widths=None):
        body = [[cell(x) for x in headers]] + [[cell(x) for x in row] for row in rows]
        available_width = landscape(A4)[0] - 24*mm
        if widths is None and headers:
            widths = [available_width / len(headers)] * len(headers)
        t = Table(body, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#17365D")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#CBD5E1")),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 4), ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ]))
        return t

    f = data["filters"]
    summary = data["summary"]
    story = [Paragraph("Informe ejecutivo de Contraloría — SICAS", styles["SicasTitle"]),
             Paragraph(escape(f"Período: {f.get('start_date')} a {f.get('end_date')} | Dominio: {f.get('audit_domain') or 'Todos'} | Unidad: {f.get('unit_id') or 'Todas'}"), styles["BodyText"]),
             Paragraph("Los tiempos de fase son tiempo transcurrido, no horas activas. Las observaciones generales sin ítem se muestran de forma separada.", styles["Italic"]), Spacer(1, 7)]
    headline_rows = [
        ["Auditorías", summary.get("audits_total")],
        ["En curso", summary.get("audits_in_progress")],
        ["Cerradas de cohorte", summary.get("audits_closed")],
        ["Brechas abiertas", summary.get("observations_open")],
        ["Brechas alto/crítico", summary.get("high_risk_observations")],
        ["Alertas prioritarias mostradas", data.get("alert_summary", {}).get("total", 0)],
        ["Incidencias de calidad", data.get("data_quality", {}).get("issues_total", 0)],
    ]
    story.append(table(["Indicador", "Valor"], headline_rows))

    domain_rows = [[r.get("audit_domain"), r.get("audits_total"), r.get("audits_in_progress"), r.get("audits_closed"),
                    r.get("observations_total"), r.get("observations_open"), r.get("critical_observations"), r.get("high_risk_observations"),
                    f"{r.get('items_scored',0)}/{r.get('items_total',0)}", r.get("items_scored_pct")] for r in data.get("by_domain", [])]
    story += [Paragraph("Comparación FINANCIERA vs SISTEMAS", styles["SicasSection"]),
              table(["Dominio","Auditorías","En curso","Cerradas","Brechas","Abiertas","Críticas","Altas","Ítems calificados/total","% calificados"], domain_rows)]

    alert_rows = [[a.get("severity"), a.get("alert_type"), a.get("audit_code"), a.get("domain"), a.get("unit_name"), a.get("detail"), a.get("due_date"), a.get("days_overdue")] for a in data.get("alerts", [])[:80]]
    story += [Paragraph("Centro de alertas y vencimientos (hasta 80 principales)", styles["SicasSection"]),
              table(["Nivel","Tipo","Auditoría","Dominio","Unidad","Detalle","Vencimiento","Antigüedad días"], alert_rows)]

    quality_rows = [[c.get("level"),c.get("label"),c.get("count"),c.get("description")] for c in data.get("data_quality",{}).get("checks",[])]
    story += [Paragraph("Calidad e integridad de datos", styles["SicasSection"]),
              table(["Nivel","Control","Cantidad","Interpretación"],quality_rows)]
    phase_rows = [[v.get("phase"),v.get("audits"),v.get("overdue"),v.get("average_phase_hours")] for v in data.get("phase_pipeline",{}).get("phases",[])]
    story += [Paragraph("Flujo de auditoría",styles["SicasSection"]),
              table(["Fase","Auditorías activas","Vencidas","Promedio horas transcurridas"],phase_rows)]
    work_rows = [[v.get("auditor_name"),v.get("active_audits"),v.get("overdue_audits"),v.get("open_high_risk"),v.get("average_open_age_days"),v.get("tracked_active_hours"),v.get("tracked_sessions")] for v in data.get("workload",[])]
    story += [Paragraph("Carga asignada y tiempo activo registrado por auditores",styles["SicasSection"]),
              table(["Auditor","Auditorías activas","Vencidas","Brechas alto/crítico abiertas","Edad promedio días hábiles","Horas hábiles activas registradas","Sesiones"],work_rows)]
    kpi_rows = [[k.get("name"),k.get("metric",{}).get("label"),k.get("actual_value"),k.get("target_value"),k.get("warning_value"),k.get("status_result"),k.get("period_start"),k.get("period_end")] for k in kpis]
    story += [Paragraph("KPI configurables",styles["SicasSection"]),
              table(["KPI","Métrica","Real","Meta","Advertencia","Resultado","Inicio","Fin"],kpi_rows)]

    def footer(canvas, current_doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(12*mm, 7*mm, "SICAS — Informe agregado de Contraloría")
        canvas.drawRightString(landscape(A4)[0]-12*mm, 7*mm, f"Página {current_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    output.seek(0)
    return output


def render_print_report(data: dict[str, Any], kpis: list[dict[str, Any]]) -> str:
    """Informe HTML imprimible; el navegador permite Guardar como PDF sin dependencia externa."""
    s = data["summary"]
    filt = data["filters"]
    title = "Informe ejecutivo de Contraloría — SICAS"
    cards = [("Auditorías", s.get("audits_total")), ("En curso", s.get("audits_in_progress")),
             ("Cerradas de la cohorte", s.get("audits_closed")), ("Brechas abiertas", s.get("observations_open")),
             ("Riesgo alto/crítico", s.get("high_risk_observations")), ("Alertas actuales", data.get("alert_summary", {}).get("total")),
             ("Incidencias de calidad", data.get("data_quality", {}).get("issues_total"))]
    card_html = "".join(f"<div class='card'><span>{html.escape(str(k))}</span><strong>{html.escape('—' if v is None else str(v))}</strong></div>" for k,v in cards)
    domain_rows = [[r.get("audit_domain"), r.get("audits_total"), r.get("audits_in_progress"), r.get("audits_closed"),
                    r.get("observations_total"), r.get("observations_open"), r.get("critical_observations"), r.get("high_risk_observations"),
                    r.get("items_scored"), r.get("items_total"), r.get("items_scored_pct")] for r in data.get("by_domain", [])]
    alert_rows = [[r.get("severity"), r.get("alert_type"), r.get("audit_code"), r.get("domain"), r.get("unit_name"), r.get("detail"), r.get("due_date"), r.get("days_overdue")] for r in data.get("alerts", [])[:50]]
    quality_rows = [[r.get("level"), r.get("label"), r.get("count"), r.get("description")] for r in data.get("data_quality", {}).get("checks", [])]
    phase_rows = [[r.get("phase"), r.get("audits"), r.get("overdue"), r.get("average_phase_hours")] for r in data.get("phase_pipeline", {}).get("phases", [])]
    workload_rows = [[r.get("auditor_name"), r.get("active_audits"), r.get("overdue_audits"), r.get("open_high_risk"), r.get("average_open_age_days"), r.get("tracked_active_hours"), r.get("tracked_sessions")] for r in data.get("workload", [])]
    kpi_rows = [[k.get("name"), k.get("metric", {}).get("label"), k.get("actual_value"), k.get("target_value"), k.get("warning_value"), k.get("status_result"), k.get("period_start"), k.get("period_end")] for k in kpis]
    sections = [
        ("Comparación FINANCIERA vs SISTEMAS", _report_table(["Dominio","Auditorías","En curso","Cerradas","Brechas","Abiertas","Críticas","Altas","Ítems calificados","Ítems totales","% calificados"], domain_rows)),
        ("Centro de alertas (hasta 50 principales)", _report_table(["Nivel","Tipo","Auditoría","Dominio","Unidad","Detalle","Vencimiento","Antigüedad días"], alert_rows)),
        ("Calidad e integridad", _report_table(["Tipo","Control","Cantidad","Interpretación"], quality_rows)),
        ("Flujo de auditoría", _report_table(["Fase","Auditorías activas","Vencidas","Horas hábiles transcurridas promedio"], phase_rows)),
        ("Carga asignada de auditores", _report_table(["Auditor","Auditorías activas","Vencidas","Brechas altas abiertas","Edad promedio (días hábiles)"], workload_rows)),
        ("KPI y metas", _report_table(["KPI","Métrica","Real","Meta","Advertencia","Resultado","Inicio","Fin"], kpi_rows)),
    ]
    section_html = "".join(f"<section><h2>{html.escape(h)}</h2>{body}</section>" for h,body in sections)
    filters_html = html.escape(f"Período {filt.get('start_date')} a {filt.get('end_date')} | Dominio: {filt.get('audit_domain') or 'Todos'} | Unidad ID: {filt.get('unit_id') or 'Todas'} | Auditor: {filt.get('auditor_id') or 'Todos'}")
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title>
<style>body{{font:14px Arial,sans-serif;color:#182435;margin:24px}}h1{{font-size:24px}}h2{{font-size:17px;border-bottom:1px solid #c8d2e0;padding-bottom:5px;margin-top:28px}}.muted{{color:#536274}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:20px 0}}.card{{border:1px solid #d5dce5;border-radius:6px;padding:10px;display:grid;gap:7px}}.card strong{{font-size:21px}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;font-size:11px;margin:9px 0 18px}}th,td{{border:1px solid #ccd4df;padding:5px;text-align:left;vertical-align:top}}th{{background:#eaf0f7}}button{{padding:10px 16px;margin-bottom:14px}}@media print{{body{{margin:10mm}}button{{display:none}}section{{break-inside:avoid}}h2{{break-after:avoid}}.table-wrap{{overflow:visible}}}}</style></head><body>
<button onclick='window.print()'>Imprimir / Guardar como PDF</button><h1>{html.escape(title)}</h1><p class='muted'>{filters_html}</p><p class='muted'>Generado: {html.escape(datetime.now(timezone.utc).isoformat())}. Los tiempos por fase son transcurridos; no representan horas activas de trabajo. Las observaciones generales sin ítem se mantienen diferenciadas.</p><div class='cards'>{card_html}</div>{section_html}</body></html>"""


def get_dashboard_data(filters: dict[str, Any]) -> dict[str, Any]:
    params = {k: filters[k] for k in ("start_at", "end_before", "unit_id", "auditor_id", "audit_domain")}
    by_domain = _get_domain_comparison(filters)
    summary = _one(SCOPE_CTE + f"""
        SELECT count(*)::integer AS audits_total,
               (count(*) FILTER (WHERE {IN_PROGRESS_SQL}))::integer AS audits_in_progress,
               (count(*) FILTER (WHERE {CLOSED_SQL}))::integer AS audits_closed,
               round((avg(s.elapsed_days) FILTER (WHERE {CLOSED_SQL}))::numeric, 2) AS avg_closed_audit_days,
               round((avg(s.elapsed_days) FILTER (WHERE NOT ({CLOSED_SQL})))::numeric, 2) AS avg_open_days
        FROM audit_scope s
    """, params)
    summary["pending_approval"] = int(db.session.execute(text(SCOPE_CTE + """
        SELECT count(DISTINCT r.id)::integer
        FROM engagement.reports r JOIN audit_scope s ON s.id = r.audit_id
        WHERE upper(coalesce(r.status,'')) IN ('IN_REVIEW','GERENCIA','CONTRALOR','SUBMITTED','PENDING')
    """), params).scalar_one())

    risks = _mappings(OBS_CTE + """
        SELECT risk_bucket, count(*)::integer AS total,
               (count(*) FILTER (WHERE is_open))::integer AS open_total
        FROM observation_scope GROUP BY risk_bucket ORDER BY risk_bucket
    """, params)
    risk_map = {r["risk_bucket"]: {"total": r["total"], "open": r["open_total"]} for r in risks}
    for key in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNSPECIFIED", "OTHER"):
        risk_map.setdefault(key, {"total": 0, "open": 0})
    summary["observations_total"] = sum(item["total"] for item in risk_map.values())
    summary["observations_open"] = sum(item["open"] for item in risk_map.values())
    summary["high_risk_observations"] = risk_map["CRITICAL"]["total"] + risk_map["HIGH"]["total"]

    unit_audits = _mappings(SCOPE_CTE + f"""
        SELECT s.unit_id, s.unit_code, s.unit_name,
               count(DISTINCT s.id)::integer AS audits_total,
               (count(DISTINCT s.id) FILTER (WHERE {IN_PROGRESS_SQL}))::integer AS audits_in_progress,
               (count(DISTINCT s.id) FILTER (WHERE {CLOSED_SQL}))::integer AS audits_closed,
               round((avg(s.elapsed_days) FILTER (WHERE {CLOSED_SQL}))::numeric, 2) AS avg_closed_audit_days
        FROM audit_scope s
        GROUP BY s.unit_id, s.unit_code, s.unit_name
    """, params)
    unit_observations = _mappings(OBS_CTE + """
        SELECT unit_id, unit_code, unit_name,
               count(*)::integer AS observations_total,
               (count(*) FILTER (WHERE risk_bucket IN ('HIGH','CRITICAL')))::integer AS high_risk_observations,
               (count(*) FILTER (WHERE is_open))::integer AS observations_open
        FROM observation_scope
        GROUP BY unit_id, unit_code, unit_name
    """, params)
    unit_map: dict[int | None, dict[str, Any]] = {}
    for row in unit_audits:
        target = _empty_unit(row["unit_id"], row["unit_code"], row["unit_name"])
        target.update({k: row[k] for k in ("audits_total", "audits_in_progress", "audits_closed", "avg_closed_audit_days")})
        unit_map[row["unit_id"]] = target

    for row in unit_observations:
        target = unit_map.setdefault(row["unit_id"], _empty_unit(row["unit_id"], row["unit_code"], row["unit_name"]))
        target.update({k: row[k] for k in ("observations_total", "high_risk_observations", "observations_open")})

    unit_risks = _mappings(OBS_CTE + """
        SELECT unit_id, unit_code, unit_name, risk_bucket, count(*)::integer AS total
        FROM observation_scope
        GROUP BY unit_id, unit_code, unit_name, risk_bucket
    """, params)
    for row in unit_risks:
        target = unit_map.setdefault(row["unit_id"], _empty_unit(row["unit_id"], row["unit_code"], row["unit_name"]))
        target["risk_breakdown"][row["risk_bucket"]] = row["total"]

    by_unit = sorted(unit_map.values(), key=lambda r: (-r["high_risk_observations"], -r["observations_total"], r["unit_name"]))

    bucket = _period_expression(filters["granularity"])
    audit_trend = _mappings(SCOPE_CTE + f"""
        SELECT {bucket} AS period_start,
               count(*)::integer AS audits_total,
               (count(*) FILTER (WHERE {CLOSED_SQL}))::integer AS audits_closed
        FROM audit_scope s
        GROUP BY period_start ORDER BY period_start
    """, params)
    observation_bucket = _period_expression(filters["granularity"], alias="o")
    observation_trend = _mappings(OBS_CTE + f"""
        SELECT {observation_bucket} AS period_start, count(*)::integer AS observations_total
        FROM observation_scope o
        GROUP BY period_start ORDER BY period_start
    """, params)
    trend_map: dict[date, dict[str, Any]] = {}
    for row in audit_trend:
        key = _period_key(row["period_start"])
        trend_map[key] = {"period_start": row["period_start"], "audits_total": row["audits_total"],
                          "audits_closed": row["audits_closed"], "observations_total": 0}
    for row in observation_trend:
        key = _period_key(row["period_start"])
        entry = trend_map.setdefault(key, {"period_start": row["period_start"], "audits_total": 0,
                                           "audits_closed": 0, "observations_total": 0})
        entry["observations_total"] = row["observations_total"]
    first_period = _period_floor(filters["start_date"], filters["granularity"])
    last_period = _period_floor(filters["end_date"], filters["granularity"])
    key = first_period
    while key <= last_period:
        trend_map.setdefault(key, {"period_start": key, "audits_total": 0,
                                   "audits_closed": 0, "observations_total": 0})
        key = _next_period(key, filters["granularity"])
    trend = [trend_map[key] for key in sorted(trend_map)]

    phase_times = _mappings(SCOPE_CTE + """, phase_entries AS (
        SELECT pl.id, pl.audit_id, coalesce(nullif(pl.to_phase,''),'SIN_FASE') AS phase,
               pl.changed_at, s.status, s.pac_sent_at,
               lead(pl.changed_at) OVER (PARTITION BY pl.audit_id ORDER BY pl.changed_at, pl.id) AS next_at
        FROM engagement.phase_log pl JOIN audit_scope s ON s.id = pl.audit_id
    ), phase_durations AS (
        SELECT phase,
               CASE
                 WHEN next_at IS NOT NULL
                   THEN greatest(engagement.business_seconds(changed_at, next_at) / 3600.0, 0)
                 WHEN upper(coalesce(status, '')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
                      AND pac_sent_at IS NOT NULL
                   THEN greatest(engagement.business_seconds(changed_at, pac_sent_at) / 3600.0, 0)
                 WHEN upper(coalesce(status, '')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
                   THEN greatest(engagement.business_seconds(changed_at, CURRENT_TIMESTAMP) / 3600.0, 0)
                 ELSE NULL
               END AS duration_hours
        FROM phase_entries
    )
    SELECT phase, count(*)::integer AS transitions,
           round(avg(duration_hours)::numeric, 2) AS average_hours
    FROM phase_durations GROUP BY phase ORDER BY phase
    """, params)

    auditors = _mappings(SCOPE_CTE + f""", auditor_audits AS (
        SELECT DISTINCT u.id AS auditor_id, coalesce(nullif(u.full_name,''),u.username) AS auditor_name,
               s.id AS audit_id, s.status, s.elapsed_days
        FROM audit_scope s JOIN engagement.team t ON t.audit_id = s.id
        JOIN iam.users u ON u.id = t.user_id
    )
    SELECT auditor_id::text, auditor_name,
           count(DISTINCT audit_id)::integer AS audits_total,
           (count(DISTINCT audit_id) FILTER (WHERE upper(coalesce(status,'')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')))::integer AS audits_closed,
           round((avg(elapsed_days) FILTER (WHERE upper(coalesce(status,'')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')))::numeric, 2) AS avg_closed_audit_days
    FROM auditor_audits GROUP BY auditor_id, auditor_name
    ORDER BY audits_total DESC, auditor_name
    """, params)

    if filters.get("_domain_locked"):
        ingestion = None
    else:
        ingestion_params = {
            "start_at": filters["start_at"],
            "end_before": filters["end_before"],
            "auditor_id": filters["auditor_id"],
        }
        ingestion = _one("""
            SELECT count(*)::integer AS jobs_total,
                   (count(*) FILTER (WHERE upper(status)='FAILED'))::integer AS jobs_failed,
                   (count(*) FILTER (WHERE upper(status) IN ('QUEUED','PROCESSING','RUNNING')))::integer AS jobs_in_progress,
                   coalesce(sum(rows_total),0)::bigint AS rows_total,
                   coalesce(sum(rows_processed),0)::bigint AS rows_processed,
                   coalesce(sum(rows_rejected),0)::bigint AS rows_rejected,
                   round((avg(extract(epoch FROM (finished_at-created_at))) FILTER (WHERE finished_at IS NOT NULL AND finished_at >= created_at))::numeric, 2) AS average_seconds
            FROM insurance.ingestion_jobs j
            WHERE j.created_at >= :start_at AND j.created_at < :end_before
              AND (CAST(:auditor_id AS uuid) IS NULL OR j.uploaded_by = CAST(:auditor_id AS uuid))
        """, ingestion_params)
        ingestion["rejection_pct"] = _safe_pct(ingestion["rows_rejected"], ingestion["rows_processed"] + ingestion["rows_rejected"])

    alerts = get_control_alerts(filters)
    data_quality = get_data_quality(filters)
    phase_pipeline = get_workflow_pipeline(filters)
    workload = get_auditor_workload(filters)
    alert_summary = {
        "total": len(alerts),
        "critical": sum(1 for a in alerts if a["severity"] == "CRITICA"),
        "high": sum(1 for a in alerts if a["severity"] == "ALTA"),
        "medium": sum(1 for a in alerts if a["severity"] == "MEDIA"),
        "overdue": sum(1 for a in alerts if a["alert_type"] in {"AUDITORIA_VENCIDA", "PAC_VENCIDO"}),
    }
    return {
        "filters": {
            "start_date": filters["start_date"].isoformat(),
            "end_date": filters["end_date"].isoformat(),
            "unit_id": filters["unit_id"],
            "auditor_id": filters["auditor_id"],
            "audit_domain": filters["audit_domain"],
            "granularity": filters["granularity"],
        },
        "summary": summary,
        "observations_by_risk": risk_map,
        "by_domain": by_domain,
        "by_unit": by_unit,
        "trend": trend,
        "phase_times": phase_times,
        "by_auditor": auditors,
        "ingestion": ingestion,
        "metric_catalog": METRICS,
        "alerts": alerts,
        "alert_summary": alert_summary,
        "data_quality": data_quality,
        "phase_pipeline": phase_pipeline,
        "workload": workload,
    }


def _excel_safe_text(value: Any) -> Any:
    """Prevent Excel formula injection in text originating from application data."""
    if not isinstance(value, str):
        return value
    if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _safe_pct(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round((float(numerator) / float(denominator)) * 100.0, 2)


def get_options(audit_domain: str | None = None) -> dict[str, Any]:
    params = {"audit_domain": audit_domain}
    units = _mappings("""
        SELECT DISTINCT u.id, u.code, u.name
        FROM engagement.units u
        WHERE u.active IS TRUE
          AND (CAST(:audit_domain AS text) IS NULL OR EXISTS (
              SELECT 1
              FROM engagement.audits a
              JOIN engagement.files f ON f.id = a.file_id
              WHERE f.unit_id = u.id
                AND upper(coalesce(a.audit_domain, '')) = CAST(:audit_domain AS text)
          ))
        ORDER BY u.name
    """, params)
    auditors = _mappings("""
        SELECT DISTINCT u.id::text AS id,
               coalesce(nullif(u.full_name,''),u.username) AS name
        FROM engagement.team t
        JOIN iam.users u ON u.id = t.user_id
        WHERE u.is_active IS TRUE
          AND (CAST(:audit_domain AS text) IS NULL OR EXISTS (
              SELECT 1
              FROM engagement.audits a
              WHERE a.id = t.audit_id
                AND upper(coalesce(a.audit_domain, '')) = CAST(:audit_domain AS text)
          ))
        ORDER BY name
    """, params)
    domains = [r["audit_domain"] for r in _mappings("""
        SELECT DISTINCT upper(audit_domain) AS audit_domain
        FROM engagement.audits
        WHERE nullif(trim(audit_domain),'') IS NOT NULL
          AND (CAST(:audit_domain AS text) IS NULL OR upper(audit_domain) = CAST(:audit_domain AS text))
        ORDER BY 1
    """, params)]
    return {"units": units, "auditors": auditors, "domains": domains}
def period_window(periodicity: str, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    period = periodicity.upper()
    if period == "MENSUAL":
        start = date(today.year, today.month, 1)
    elif period == "TRIMESTRAL":
        start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
    elif period == "SEMESTRAL":
        start = date(today.year, 1 if today.month <= 6 else 7, 1)
    elif period == "ANUAL":
        start = date(today.year, 1, 1)
    else:
        raise ValueError("Periodicidad de KPI no válida.")
    return start, today


def _filter_for_period(
    start: date,
    end: date,
    unit_id: int | None = None,
    auditor_id: str | None = None,
    audit_domain: str | None = None,
) -> dict[str, Any]:
    return {
        "start_date": start,
        "end_date": end,
        "start_at": datetime.combine(start, time.min, tzinfo=timezone.utc),
        "end_before": datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc),
        "unit_id": unit_id,
        "auditor_id": auditor_id,
        "audit_domain": audit_domain,
        "granularity": "MONTH",
    }

def metric_value(metric_code: str, filters: dict[str, Any]) -> float | None:
    if metric_code not in METRICS:
        raise ValueError("La métrica seleccionada no está permitida.")
    params = {k: filters[k] for k in ("start_at", "end_before", "unit_id", "auditor_id", "audit_domain")}
    if metric_code in {"AUDITS_TOTAL", "AUDITS_IN_PROGRESS", "AUDITS_CLOSED", "AUDIT_COMPLETION_PCT", "AVG_CLOSED_AUDIT_DAYS"}:
        if metric_code == "AUDITS_TOTAL": expr = "count(*)::numeric"
        elif metric_code == "AUDITS_IN_PROGRESS": expr = f"(count(*) FILTER (WHERE {IN_PROGRESS_SQL}))::numeric"
        elif metric_code == "AUDITS_CLOSED": expr = f"(count(*) FILTER (WHERE {CLOSED_SQL}))::numeric"
        elif metric_code == "AUDIT_COMPLETION_PCT": expr = f"100.0 * count(*) FILTER (WHERE {CLOSED_SQL}) / NULLIF(count(*),0)"
        else: expr = f"avg(s.elapsed_days) FILTER (WHERE {CLOSED_SQL})"
        value = db.session.execute(text(SCOPE_CTE + f" SELECT {expr} AS value FROM audit_scope s"), params).scalar_one()
    elif metric_code in {"OBSERVATIONS_TOTAL", "HIGH_RISK_OBSERVATIONS", "HIGH_RISK_SHARE_PCT"}:
        if metric_code == "OBSERVATIONS_TOTAL": expr = "count(*)::numeric"
        elif metric_code == "HIGH_RISK_OBSERVATIONS": expr = "(count(*) FILTER (WHERE risk_bucket IN ('HIGH','CRITICAL')))::numeric"
        else: expr = "100.0 * count(*) FILTER (WHERE risk_bucket IN ('HIGH','CRITICAL')) / NULLIF(count(*),0)"
        value = db.session.execute(text(OBS_CTE + f" SELECT {expr} AS value FROM observation_scope"), params).scalar_one()
    elif metric_code == "AVG_PHASE_HOURS":
        value = db.session.execute(text(SCOPE_CTE + """, phase_entries AS (
            SELECT pl.changed_at, s.status, s.pac_sent_at,
                   lead(pl.changed_at) OVER (PARTITION BY pl.audit_id ORDER BY pl.changed_at, pl.id) AS next_at
            FROM engagement.phase_log pl JOIN audit_scope s ON s.id=pl.audit_id
        ), phase_durations AS (
            SELECT CASE
                     WHEN next_at IS NOT NULL
                       THEN greatest(engagement.business_seconds(changed_at, next_at) / 3600.0, 0)
                     WHEN upper(coalesce(status, '')) IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
                          AND pac_sent_at IS NOT NULL
                       THEN greatest(engagement.business_seconds(changed_at, pac_sent_at) / 3600.0, 0)
                     WHEN upper(coalesce(status, '')) NOT IN ('CLOSED','COMPLETED','SIGNED','CERRADO','CERRADA')
                       THEN greatest(engagement.business_seconds(changed_at, CURRENT_TIMESTAMP) / 3600.0, 0)
                     ELSE NULL
                   END AS duration_hours
            FROM phase_entries
        ) SELECT avg(duration_hours) AS value FROM phase_durations
        """), params).scalar_one()
    else:
        ingestion_params = {"start_at": filters["start_at"], "end_before": filters["end_before"], "auditor_id": filters["auditor_id"]}
        if metric_code == "INGESTION_AVG_SECONDS":
            sql = """SELECT avg(extract(epoch FROM (finished_at-created_at))) AS value FROM insurance.ingestion_jobs j
                     WHERE j.created_at>=:start_at AND j.created_at<:end_before
                     AND finished_at IS NOT NULL AND finished_at>=created_at
                     AND (CAST(:auditor_id AS uuid) IS NULL OR uploaded_by=CAST(:auditor_id AS uuid))"""
        else:
            sql = """SELECT 100.0*coalesce(sum(rows_rejected),0)/NULLIF(coalesce(sum(rows_processed),0)+coalesce(sum(rows_rejected),0),0) AS value
                     FROM insurance.ingestion_jobs j WHERE j.created_at>=:start_at AND j.created_at<:end_before
                     AND (CAST(:auditor_id AS uuid) IS NULL OR uploaded_by=CAST(:auditor_id AS uuid))"""
        value = db.session.execute(text(sql), ingestion_params).scalar_one()
    if value is None:
        return None
    result = float(value)
    return round(result, 2) if isfinite(result) else None


def _auditor_belongs_to_domain(auditor_id: str, audit_domain: str) -> bool:
    domain = str(audit_domain or "").strip().upper()
    if domain not in {"FINANCIERA", "SISTEMAS"}:
        return False
    try:
        auditor_uuid = str(UUID(str(auditor_id)))
    except (TypeError, ValueError, AttributeError):
        return False
    return bool(db.session.execute(text("""
        SELECT EXISTS (
            SELECT 1
            FROM engagement.team t
            JOIN engagement.audits a ON a.id = t.audit_id
            WHERE t.user_id = CAST(:auditor_id AS uuid)
              AND upper(coalesce(a.audit_domain, '')) = CAST(:audit_domain AS text)
        )
    """), {"auditor_id": auditor_uuid, "audit_domain": domain}).scalar_one())


def _validate_kpi(payload: dict[str, Any], audit_domain: str | None = None) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name or len(name) > 120:
        raise ValueError("El nombre del KPI es obligatorio y debe tener máximo 120 caracteres.")
    description = str(payload.get("description") or "").strip()
    if len(description) > 1000:
        raise ValueError("La descripción debe tener máximo 1000 caracteres.")
    metric_code = str(payload.get("metric_code") or "").strip().upper()
    if metric_code not in METRICS:
        raise ValueError("Seleccione una métrica del catálogo autorizado.")
    direction = str(payload.get("direction") or "AT_LEAST").strip().upper()
    if direction not in DIRECTIONS:
        raise ValueError("La dirección debe ser AT_LEAST o AT_MOST.")
    periodicity = str(payload.get("periodicity") or "MENSUAL").strip().upper()
    if periodicity not in PERIODICITIES:
        raise ValueError("Seleccione una periodicidad válida.")
    scope_type = str(payload.get("scope_type") or "GENERAL").strip().upper()
    if scope_type not in SCOPES:
        raise ValueError("Seleccione un alcance válido.")

    target_raw = payload.get("target_value")
    try:
        if isinstance(target_raw, bool):
            raise ValueError
        target = float(target_raw)
        if not isfinite(target) or target < 0:
            raise ValueError
        if METRICS[metric_code]["unit"] == "%" and target > 100:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("La meta debe ser un número válido, no negativo y no mayor que 100 si es porcentaje.") from exc

    warning_raw = payload.get("warning_value")
    try:
        if isinstance(warning_raw, bool):
            raise ValueError
        warning = None if warning_raw in (None, "") else float(warning_raw)
        if warning is not None and (not isfinite(warning) or warning < 0):
            raise ValueError
        if warning is not None and METRICS[metric_code]["unit"] == "%" and warning > 100:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("El umbral debe ser no negativo y no mayor que 100 si es porcentaje.") from exc
    if warning is not None and ((direction == "AT_LEAST" and warning > target) or (direction == "AT_MOST" and warning < target)):
        raise ValueError("Para AT_LEAST la advertencia debe ser menor o igual a la meta; para AT_MOST debe ser mayor o igual.")

    unit_raw = payload.get("unit_id")
    auditor_id = payload.get("auditor_id")
    try:
        if unit_raw is None or unit_raw == "":
            unit_id = None
        elif isinstance(unit_raw, bool):
            raise ValueError
        elif isinstance(unit_raw, int):
            unit_id = unit_raw
        elif isinstance(unit_raw, float):
            if not isfinite(unit_raw) or not unit_raw.is_integer():
                raise ValueError
            unit_id = int(unit_raw)
        elif isinstance(unit_raw, str):
            unit_id = int(unit_raw.strip())
        else:
            raise ValueError
        if unit_id is not None and unit_id < 1:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("La unidad elegida no es válida.") from exc

    if auditor_id not in (None, ""):
        try:
            auditor_id = str(UUID(str(auditor_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("El auditor elegido no es válido.") from exc
    else:
        auditor_id = None

    if (scope_type == "GENERAL" and (unit_id is not None or auditor_id is not None)) or (scope_type == "UNIDAD" and (unit_id is None or auditor_id is not None)) or (scope_type == "AUDITOR" and (auditor_id is None or unit_id is not None)):
        raise ValueError("Seleccione únicamente el alcance requerido: general, unidad o auditor.")
    if scope_type == "UNIDAD" and metric_code in {"INGESTION_AVG_SECONDS", "INGESTION_REJECTION_PCT"}:
        raise ValueError("Las tablas actuales de cargas no identifican una unidad; cree este KPI con alcance general o por auditor.")

    if audit_domain is not None:
        domain = str(audit_domain).strip().upper()
        if domain not in {"FINANCIERA", "SISTEMAS"}:
            raise ValueError("No se pudo determinar un único dominio de auditoría para este usuario.")
        if scope_type != "AUDITOR" or unit_id is not None or auditor_id is None:
            raise ValueError("Los jefes solo pueden crear KPI con alcance de auditor individual.")
        if metric_code in {"INGESTION_AVG_SECONDS", "INGESTION_REJECTION_PCT"}:
            raise ValueError("Esta métrica de cargas no está separada por dominio y no puede usarse en KPI de jefatura.")
        if not _auditor_belongs_to_domain(auditor_id, domain):
            raise ValueError("El auditor seleccionado no pertenece al dominio supervisado por este jefe.")

    return {"name": name, "description": description, "metric_code": metric_code, "target_value": target,
            "warning_value": warning, "direction": direction, "periodicity": periodicity,
            "scope_type": scope_type, "unit_id": unit_id, "auditor_id": auditor_id}

def _kpi_status(actual: float | None, target: float, warning: float | None, direction: str) -> str:
    if actual is None: return "SIN_DATOS"
    met = actual >= target if direction == "AT_LEAST" else actual <= target
    if met: return "CUMPLIDO"
    if warning is not None:
        in_warning = actual >= warning if direction == "AT_LEAST" else actual <= warning
        if in_warning: return "ATENCION"
    return "DESVIACION"


def list_kpis(
    include_inactive: bool = False,
    as_of: date | None = None,
    owner_id: str | None = None,
    audit_domain: str | None = None,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if not include_inactive:
        conditions.append("k.active IS TRUE")
    if owner_id is not None:
        params["owner_id"] = str(UUID(str(owner_id)))
        conditions.append("k.created_by = CAST(:owner_id AS uuid)")
    if audit_domain is not None:
        domain = str(audit_domain).strip().upper()
        if domain not in {"FINANCIERA", "SISTEMAS"}:
            raise ValueError("Dominio de auditoría no válido.")
        params["audit_domain"] = domain
        conditions.extend([
            "k.scope_type = 'AUDITOR'",
            "k.metric_code NOT IN ('INGESTION_AVG_SECONDS','INGESTION_REJECTION_PCT')",
            "EXISTS (SELECT 1 FROM engagement.team kt "
            "JOIN engagement.audits ka ON ka.id=kt.audit_id "
            "WHERE kt.user_id=k.auditor_id "
            "AND upper(coalesce(ka.audit_domain,''))=CAST(:audit_domain AS text))",
        ])
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    rows = _mappings(f"""
        SELECT k.id::text AS id, k.name, k.description, k.metric_code, k.target_value,
               k.warning_value, k.direction, k.periodicity, k.scope_type, k.unit_id,
               k.auditor_id::text AS auditor_id, k.active, k.created_at,
               coalesce(u.name, '') AS unit_name,
               coalesce(nullif(i.full_name,''), i.username, '') AS auditor_name
        FROM analytics.kpi_definitions k
        LEFT JOIN engagement.units u ON u.id=k.unit_id
        LEFT JOIN iam.users i ON i.id=k.auditor_id
        {where}
        ORDER BY k.active DESC, k.created_at DESC LIMIT 100
    """, params)
    for row in rows:
        actual = None
        period_start, period_end = period_window(row["periodicity"], as_of)
        if row["active"]:
            filters = _filter_for_period(
                period_start,
                period_end,
                row["unit_id"] if row["scope_type"] == "UNIDAD" else None,
                row["auditor_id"] if row["scope_type"] == "AUDITOR" else None,
                audit_domain=audit_domain,
            )
            actual = metric_value(row["metric_code"], filters)
        target = float(row["target_value"])
        warning = float(row["warning_value"]) if row["warning_value"] is not None else None
        row["target_value"] = target
        row["warning_value"] = warning
        row["actual_value"] = actual
        row["period_start"] = period_start.isoformat()
        row["period_end"] = period_end.isoformat()
        row["status_result"] = _kpi_status(actual, target, warning, row["direction"]) if row["active"] else "INACTIVO"
        row["metric"] = METRICS[row["metric_code"]]
    return rows

_KPI_AUDIT_FIELDS = (
    "name", "description", "metric_code", "target_value", "warning_value", "direction",
    "periodicity", "scope_type", "unit_id", "auditor_id", "active",
)


def _kpi_audit_snapshot(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return {key: value[key] for key in _KPI_AUDIT_FIELDS if key in value}


def _write_kpi_audit(action: str, kpi_id: str, before: Any = None, after: Any = None) -> None:
    """Best-effort audit event, called only after the KPI transaction is committed."""
    from flask import g, has_request_context
    from app.core.audit.audit_service import audit as audit_event

    try:
        request_id = getattr(g, "request_id", None) if has_request_context() else None
        audit_event(
            action=action,
            outcome="SUCCESS",
            entity_type="kpi",
            entity_id=str(kpi_id),
            before_data=_kpi_audit_snapshot(before),
            after_data=_kpi_audit_snapshot(after),
            metadata={"component": "dashboard_contralor", "event_version": 1},
            request_id=request_id,
        )
    except Exception:  # noqa: BLE001 - no debe deshacer el KPI ya guardado
        import logging
        logging.getLogger("audit").exception("No se pudo registrar el evento de KPI %s", action)


def create_kpi(
    payload: dict[str, Any],
    created_by: str,
    audit_domain: str | None = None,
) -> dict[str, Any]:
    creator = str(UUID(str(created_by)))
    domain = str(audit_domain).strip().upper() if audit_domain is not None else None
    validated = _validate_kpi(payload, audit_domain=domain)
    if domain:
        count = int(db.session.execute(text("""
            SELECT count(*)
            FROM analytics.kpi_definitions k
            WHERE k.active IS TRUE
              AND k.created_by = CAST(:created_by AS uuid)
              AND k.scope_type = 'AUDITOR'
              AND EXISTS (
                  SELECT 1 FROM engagement.team t
                  JOIN engagement.audits a ON a.id=t.audit_id
                  WHERE t.user_id=k.auditor_id
                    AND upper(coalesce(a.audit_domain,''))=CAST(:audit_domain AS text)
              )
        """), {"created_by": creator, "audit_domain": domain}).scalar_one())
    else:
        count = int(db.session.execute(text(
            "SELECT count(*) FROM analytics.kpi_definitions WHERE active IS TRUE"
        )).scalar_one())
    if count >= 25:
        raise ValueError("Se alcanzó el máximo de 25 KPI activos para este alcance. Desactive uno antes de crear otro.")
    result = db.session.execute(text("""
        INSERT INTO analytics.kpi_definitions
          (name, description, metric_code, target_value, warning_value, direction, periodicity,
           scope_type, unit_id, auditor_id, created_by, updated_by)
        VALUES (:name, :description, :metric_code, :target_value, :warning_value, :direction, :periodicity,
                :scope_type, :unit_id, CAST(:auditor_id AS uuid), CAST(:created_by AS uuid), CAST(:created_by AS uuid))
        RETURNING id::text AS id
    """), {**validated, "created_by": creator}).mappings().one()
    db.session.commit()
    _write_kpi_audit("CONTRALOR_KPI_CREATED", result["id"], after={**validated, "active": True})
    visible = list_kpis(
        include_inactive=True,
        owner_id=creator if domain else None,
        audit_domain=domain,
    )
    return next((k for k in visible if k["id"] == result["id"]), {"id": result["id"]})

def assert_kpi_management_access(kpi_id: str, user_id: str, audit_domain: str) -> dict[str, Any]:
    domain = str(audit_domain or "").strip().upper()
    if domain not in {"FINANCIERA", "SISTEMAS"}:
        raise LookupError("KPI no encontrado.")
    owner = str(UUID(str(user_id)))
    try:
        kid = str(UUID(str(kpi_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LookupError("KPI no encontrado.") from exc
    current = db.session.execute(text("""
        SELECT * FROM analytics.kpi_definitions WHERE id=CAST(:id AS uuid)
    """), {"id": kid}).mappings().first()
    if not current:
        raise LookupError("KPI no encontrado.")
    if str(current.get("created_by")) != owner or current.get("scope_type") != "AUDITOR":
        raise LookupError("KPI no encontrado.")
    if current.get("metric_code") in {"INGESTION_AVG_SECONDS", "INGESTION_REJECTION_PCT"}:
        raise LookupError("KPI no encontrado.")
    if not current.get("auditor_id") or not _auditor_belongs_to_domain(str(current["auditor_id"]), domain):
        raise LookupError("KPI no encontrado.")
    return dict(current)


def update_kpi(
    kpi_id: str,
    payload: dict[str, Any],
    updated_by: str,
    audit_domain: str | None = None,
) -> dict[str, Any]:
    allowed_fields = {"name", "description", "metric_code", "target_value", "warning_value", "direction", "periodicity", "scope_type", "unit_id", "auditor_id", "active"}
    unknown_fields = set(payload) - allowed_fields
    if unknown_fields:
        raise ValueError("Campos no admitidos: " + ", ".join(sorted(unknown_fields)))

    domain = str(audit_domain).strip().upper() if audit_domain is not None else None
    if domain:
        current = assert_kpi_management_access(kpi_id, updated_by, domain)
    else:
        current = db.session.execute(
            text("SELECT * FROM analytics.kpi_definitions WHERE id=CAST(:id AS uuid)"),
            {"id": kpi_id},
        ).mappings().first()
        if not current:
            raise LookupError("KPI no encontrado.")
    before_snapshot = dict(current)
    merged = dict(current)
    merged.update({k: v for k, v in payload.items() if k in {"name", "description", "metric_code", "target_value", "warning_value", "direction", "periodicity", "scope_type", "unit_id", "auditor_id"}})
    if "active" in payload:
        if not isinstance(payload["active"], bool):
            raise ValueError("El estado activo debe ser verdadero o falso.")
        merged["active"] = payload["active"]
    validated = _validate_kpi(merged, audit_domain=domain)
    ownership_clause = " AND created_by=CAST(:updated_by AS uuid)" if domain else ""
    result = db.session.execute(text(f"""
        UPDATE analytics.kpi_definitions SET
          name=:name, description=:description, metric_code=:metric_code, target_value=:target_value,
          warning_value=:warning_value, direction=:direction, periodicity=:periodicity,
          scope_type=:scope_type, unit_id=:unit_id, auditor_id=CAST(:auditor_id AS uuid),
          active=:active, updated_by=CAST(:updated_by AS uuid), updated_at=CURRENT_TIMESTAMP
        WHERE id=CAST(:id AS uuid){ownership_clause}
    """), {**validated, "active": merged.get("active", current["active"]),
           "updated_by": str(UUID(str(updated_by))), "id": str(UUID(str(kpi_id)))} )
    if domain and result.rowcount != 1:
        db.session.rollback()
        raise LookupError("KPI no encontrado.")
    db.session.commit()
    _write_kpi_audit("CONTRALOR_KPI_UPDATED", kpi_id, before=before_snapshot,
                     after={**validated, "active": merged.get("active", current["active"])})
    visible = list_kpis(
        include_inactive=True,
        owner_id=str(UUID(str(updated_by))) if domain else None,
        audit_domain=domain,
    )
    return next((k for k in visible if k["id"] == str(kpi_id)), {"id": str(kpi_id)})

def export_workbook(data: dict[str, Any], kpis: list[dict[str, Any]]) -> BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    ws.append(["Dashboard del Contralor — SICAS"])
    ws.append(["Período", data["filters"]["start_date"], "a", data["filters"]["end_date"]])
    ws.append(["Dominio", data["filters"]["audit_domain"] or "Todos", "Unidad ID", data["filters"]["unit_id"] or "Todas"])
    ws.append(["Indicador", "Valor"])
    s = data["summary"]
    rows = [
        ("Auditorías totales", s["audits_total"]), ("Auditorías en curso", s["audits_in_progress"]),
        ("Auditorías cerradas", s["audits_closed"]), ("Informes pendientes de aprobación", s["pending_approval"]),
        ("Observaciones totales", s["observations_total"]), ("Observaciones abiertas", s["observations_open"]),
        ("Brechas de riesgo alto/crítico", s["high_risk_observations"]),
        ("Días hábiles promedio para cierre", s["avg_closed_audit_days"]), ("Días hábiles promedio transcurridos abiertas", s["avg_open_days"]),
        ("Cargas de datos", data["ingestion"]["jobs_total"]), ("Cargas fallidas", data["ingestion"]["jobs_failed"]),
        ("Filas procesadas", data["ingestion"]["rows_processed"]), ("Filas rechazadas", data["ingestion"]["rows_rejected"]),
    ]
    for row in rows: ws.append(list(row))

    domain_ws = wb.create_sheet("Comparativo por dominio")
    domain_ws.append(["Dominio", "Auditorías creadas", "En curso", "Cerradas de la cohorte", "Días hábiles promedio al cierre formal",
                      "Observaciones creadas", "Observaciones abiertas", "Crítico", "Alto", "Medio", "Bajo",
                      "Sin clasificar", "Otros", "Observaciones sin ítem", "Criterios vinculados a observaciones",
                      "Ítems de cédula", "Ítems con calificación", "% ítems calificados", "% riesgo alto/crítico"])
    for item in data.get("by_domain", []):
        row = domain_ws.max_row + 1
        domain_ws.append([
            _excel_safe_text(item["audit_domain"]), item["audits_total"], item["audits_in_progress"], item["audits_closed"],
            item["avg_closed_audit_days"], item["observations_total"], item["observations_open"],
            item["critical_observations"], item["high_risk_observations"], item["medium_observations"],
            item["low_observations"], item["unclassified_observations"], item["other_observations"],
            item["observations_without_item"], item["criteria_with_formal_observation"], item["items_total"],
            item["items_scored"], f'=IF(P{row}=0,"",Q{row}/P{row})', f'=IF(F{row}=0,"",(H{row}+I{row})/F{row})',
        ])
    for row in range(2, domain_ws.max_row + 1):
        domain_ws.cell(row, 18).number_format = "0.0%"
        domain_ws.cell(row, 19).number_format = "0.0%"
    if domain_ws.max_row > 1:
        domain_chart = BarChart()
        domain_chart.type = "bar"
        domain_chart.grouping = "stacked"
        domain_chart.overlap = 100
        domain_chart.title = "Observaciones por riesgo y dominio"
        domain_chart.y_axis.title = "Dominio"
        domain_chart.x_axis.title = "Observaciones"
        domain_chart.height, domain_chart.width = 9, 16
        domain_chart.add_data(Reference(domain_ws, min_col=8, max_col=13, min_row=1, max_row=domain_ws.max_row), titles_from_data=True)
        domain_chart.set_categories(Reference(domain_ws, min_col=1, min_row=2, max_row=domain_ws.max_row))
        domain_ws.add_chart(domain_chart, "U2")

    units = wb.create_sheet("Comparativo por unidad")
    units.append(["Unidad", "Código", "Auditorías", "En curso", "Cerradas", "Observaciones", "Alto/crítico", "Observaciones abiertas", "Días hábiles promedio al cierre", "% alto/crítico"])
    for item in data["by_unit"]:
        row = units.max_row + 1
        units.append([_excel_safe_text(item["unit_name"]), _excel_safe_text(item["unit_code"]), item["audits_total"], item["audits_in_progress"], item["audits_closed"], item["observations_total"], item["high_risk_observations"], item["observations_open"], item["avg_closed_audit_days"], f'=IF(F{row}=0,"",G{row}/F{row})'])
    units.cell(1, 10).value = "% alto/crítico"
    for row in range(2, units.max_row + 1): units.cell(row, 10).number_format = "0.0%"

    unit_risk_ws = wb.create_sheet("Riesgos por unidad")
    unit_risk_ws.append(["Unidad", "Código", "Crítico", "Alto", "Medio", "Bajo", "Sin clasificar", "Otros", "Total"])
    for item in data["by_unit"]:
        row = unit_risk_ws.max_row + 1
        breakdown = item.get("risk_breakdown") or {}
        unit_risk_ws.append([
            _excel_safe_text(item["unit_name"]), _excel_safe_text(item["unit_code"]),
            breakdown.get("CRITICAL", 0), breakdown.get("HIGH", 0), breakdown.get("MEDIUM", 0),
            breakdown.get("LOW", 0), breakdown.get("UNSPECIFIED", 0), breakdown.get("OTHER", 0), f'=SUM(C{row}:H{row})',
        ])
    if unit_risk_ws.max_row > 1:
        risk_chart = BarChart()
        risk_chart.type = "bar"
        risk_chart.grouping = "stacked"
        risk_chart.overlap = 100
        risk_chart.title = "Brechas por nivel de riesgo y unidad"
        risk_chart.y_axis.title = "Unidad"
        risk_chart.x_axis.title = "Cantidad"
        risk_chart.height, risk_chart.width = 10, 18
        risk_chart.add_data(Reference(unit_risk_ws, min_col=3, max_col=8, min_row=1, max_row=unit_risk_ws.max_row), titles_from_data=True)
        risk_chart.set_categories(Reference(unit_risk_ws, min_col=1, min_row=2, max_row=unit_risk_ws.max_row))
        unit_risk_ws.add_chart(risk_chart, "J2")

    auditor_ws = wb.create_sheet("Comparativo por auditor")
    auditor_ws.append(["Auditor", "Auditorías asignadas", "Cerradas de la cohorte", "Días hábiles promedio al cierre"])
    for item in data["by_auditor"]:
        auditor_ws.append([_excel_safe_text(item["auditor_name"]), item["audits_total"], item["audits_closed"], item["avg_closed_audit_days"]])

    risk_ws = wb.create_sheet("Brechas por riesgo")
    risk_ws.append(["Nivel de riesgo", "Total", "Abiertas"])
    known_levels = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNSPECIFIED", "OTHER"]
    extra_levels = sorted(set(data["observations_by_risk"]) - set(known_levels))
    for level in known_levels + extra_levels:
        v = data["observations_by_risk"].get(level, {"total": 0, "open": 0})
        risk_ws.append([_excel_safe_text(level), v["total"], v["open"]])

    trend_ws = wb.create_sheet("Histórico")
    trend_ws.append(["Período", "Auditorías creadas (cohorte)", "Cerradas actuales (cohorte)", "Observaciones creadas"])
    for item in data["trend"]:
        period = item["period_start"].date().isoformat() if isinstance(item["period_start"], datetime) else str(item["period_start"])
        trend_ws.append([period, item["audits_total"], item["audits_closed"], item["observations_total"]])
    if trend_ws.max_row > 1:
        chart = LineChart()
        chart.title = "Tendencia de auditorías y observaciones"
        chart.y_axis.title = "Cantidad"
        chart.x_axis.title = "Período"
        chart.height, chart.width = 8, 16
        chart.add_data(Reference(trend_ws, min_col=2, max_col=4, min_row=1, max_row=trend_ws.max_row), titles_from_data=True)
        chart.set_categories(Reference(trend_ws, min_col=1, min_row=2, max_row=trend_ws.max_row))
        trend_ws.add_chart(chart, "F2")

    chart_data = BarChart()
    chart_data.type = "bar"
    chart_data.style = 10
    chart_data.title = "Auditorías y brechas por unidad"
    chart_data.y_axis.title = "Unidad"
    chart_data.x_axis.title = "Cantidad"
    chart_data.height, chart_data.width = 10, 18
    if units.max_row > 1:
        chart_data.add_data(Reference(units, min_col=3, max_col=3, min_row=1, max_row=units.max_row), titles_from_data=True)
        chart_data.add_data(Reference(units, min_col=6, max_col=7, min_row=1, max_row=units.max_row), titles_from_data=True)
        chart_data.set_categories(Reference(units, min_col=1, min_row=2, max_row=units.max_row))
        units.add_chart(chart_data, "L2")

    phases = wb.create_sheet("Tiempos por fase")
    phases.append(["Fase", "Transiciones registradas", "Promedio horas transcurridas"])
    for item in data["phase_times"]: phases.append([_excel_safe_text(item["phase"]), item["transitions"], item["average_hours"]])

    loads = wb.create_sheet("Cargas de datos")
    loads.append(["Alcance", "Cargas", "Fallidas", "En curso", "Filas informadas", "Procesadas", "Rechazadas", "Duración promedio (seg)", "% rechazo"])
    ing = data["ingestion"]
    loads.append(["Global (las cargas no están asociadas a unidad en el esquema actual)", ing["jobs_total"], ing["jobs_failed"], ing["jobs_in_progress"], ing["rows_total"], ing["rows_processed"], ing["rows_rejected"], ing["average_seconds"], '=IF(F2+G2=0,"",G2/(F2+G2))'])
    loads["I2"].number_format = "0.0%"

    alerts_ws = wb.create_sheet("Alertas actuales")
    alerts_ws.append(["Nivel", "Tipo de alerta", "Auditoría", "Dominio", "Unidad", "Detalle", "Vencimiento", "Antigüedad (días)", "Fase"])
    for a in data.get("alerts", []):
        alerts_ws.append([_excel_safe_text(a.get("severity")), _excel_safe_text(a.get("alert_type")),
                          _excel_safe_text(a.get("audit_code")), _excel_safe_text(a.get("domain")),
                          _excel_safe_text(a.get("unit_name")), _excel_safe_text(a.get("detail")),
                          a.get("due_date"), a.get("days_overdue"), _excel_safe_text(a.get("phase"))])

    quality_ws = wb.create_sheet("Calidad de datos")
    quality_ws.append(["Código", "Control", "Cantidad", "Nivel", "Interpretación"])
    for check in data.get("data_quality", {}).get("checks", []):
        quality_ws.append([_excel_safe_text(check.get("code")), _excel_safe_text(check.get("label")),
                           check.get("count", 0), _excel_safe_text(check.get("level")),
                           _excel_safe_text(check.get("description"))])

    workflow_ws = wb.create_sheet("Flujo y carga")
    workflow_ws.append(["Sección", "Fase / persona / estado", "Auditorías activas", "Vencidas", "Riesgo alto abierto", "Promedio horas / días"])
    for phase in data.get("phase_pipeline", {}).get("phases", []):
        workflow_ws.append(["FASE", _excel_safe_text(phase.get("phase")), phase.get("audits", 0), phase.get("overdue", 0), None, phase.get("average_phase_hours")])
    for report in data.get("phase_pipeline", {}).get("pending_reports", []):
        workflow_ws.append(["INFORMES", _excel_safe_text(report.get("status")), report.get("reports", 0), None, None, None])
    for auditor_item in data.get("workload", []):
        workflow_ws.append(["CARGA AUDITOR", _excel_safe_text(auditor_item.get("auditor_name")), auditor_item.get("active_audits", 0),
                           auditor_item.get("overdue_audits", 0), auditor_item.get("open_high_risk", 0), auditor_item.get("average_open_age_days")])
        workflow_ws.append(["TIEMPO ACTIVO REGISTRADO", _excel_safe_text(auditor_item.get("auditor_name")), None, None,
                           auditor_item.get("tracked_sessions", 0), auditor_item.get("tracked_active_hours")])

    snapshots_ws = wb.create_sheet("Cortes históricos")
    snapshots_ws.append(["Fecha corte", "Capturado", "Origen", "Auditorías", "En curso", "Cerradas de cohorte", "Brechas", "Brechas abiertas", "Altas/críticas", "Incidencias de calidad", "KPIs medidos"])
    for snap in data.get("historical_snapshots", []):
        ss = snap.get("summary") or {}
        snapshots_ws.append([snap.get("snapshot_date"), snap.get("created_at"), _excel_safe_text(snap.get("source")),
            ss.get("audits_total"), ss.get("audits_in_progress"), ss.get("audits_closed"), ss.get("observations_total"),
            ss.get("observations_open"), ss.get("high_risk_observations"), (snap.get("data_quality") or {}).get("issues_total"), snap.get("kpi_count")])

    kpi_ws = wb.create_sheet("KPI")
    kpi_ws.append(["KPI", "Métrica", "Periodicidad", "Alcance", "Real", "Meta", "Umbral de advertencia", "Dirección", "Resultado", "Inicio del período", "Fin del período"])
    for item in kpis:
        row = kpi_ws.max_row + 1
        kpi_ws.append([_excel_safe_text(item["name"]), _excel_safe_text(item["metric"]["label"]), item["periodicity"], item["scope_type"], item["actual_value"], item["target_value"], item["warning_value"], item["direction"], f'=IF(E{row}="","Sin datos",IF(H{row}="AT_LEAST",IF(E{row}>=F{row},"Cumplido",IF(AND(G{row}<>"",E{row}>=G{row}),"Atención","Desviación")),IF(E{row}<=F{row},"Cumplido",IF(AND(G{row}<>"",E{row}<=G{row}),"Atención","Desviación"))))', item["period_start"], item["period_end"]])

    for sheet in wb.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions if sheet.max_row > 1 else "A1"
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
        for col in range(1, sheet.max_column + 1):
            values = [len(str(sheet.cell(r, col).value or "")) for r in range(1, min(sheet.max_row, 40) + 1)]
            sheet.column_dimensions[get_column_letter(col)].width = min(max(max(values, default=12) + 2, 12), 38)

    # Resumen como portada sin alterar las tablas de datos.
    ws["A1"].font = Font(bold=True, size=16, color="17365D")
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 22
    # Excel recalcula las fórmulas al abrir el libro.
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out
