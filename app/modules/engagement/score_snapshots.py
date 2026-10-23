"""Construcción pura de instantáneas históricas de puntuación de SICAS."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from . import scoring


def _safe(value: Any) -> Any:
    """Convierte valores de PostgreSQL a valores compatibles con JSON."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    return value


def _number(value: Any) -> float | None:
    return None if value is None else round(float(value), 2)


def build_scorecard(
    audit: dict,
    worksheets: list[dict],
    thresholds: dict | None = None,
) -> dict:
    """Captura calificaciones globales, por cédula e ítem, sin modificar datos."""
    thresholds = thresholds or scoring.DEFAULT_THRESHOLDS
    summaries = []
    worksheet_snapshots = []

    for worksheet in worksheets:
        criteria = worksheet.get("criteria") or []
        items = worksheet.get("items") or []
        summary = scoring.worksheet_summary(
            criteria,
            items,
            worksheet.get("manual_score"),
            thresholds,
        )
        summaries.append(summary)

        item_snapshots = []
        for item in items:
            results = item.get("results") or {}
            automatic = scoring.item_score(criteria, results)
            final = scoring.final_score(automatic, item.get("manual_score"))
            item_snapshots.append({
                "id": str(item.get("id") or ""),
                "ref": item.get("ref"),
                "results": _safe(results),
                "auto_score": _number(automatic),
                "final_score": _number(final),
                "manual_score": _number(item.get("manual_score")),
                "manual_reason": item.get("manual_reason"),
                "observation": item.get("observation"),
                "info_exception": item.get("info_exception"),
            })

        worksheet_snapshots.append({
            "id": str(worksheet.get("id") or ""),
            "title": worksheet.get("title") or "Cédula",
            "kind": worksheet.get("kind"),
            "line": worksheet.get("line"),
            "items": int(summary.items),
            "scored": int(summary.scored),
            "exceptions": int(summary.exceptions),
            "auto": _number(summary.auto),
            "final": _number(summary.final),
            "rating": summary.rating,
            "manual_override": bool(summary.manual_override),
            "manual_score": _number(worksheet.get("manual_score")),
            "manual_reason": worksheet.get("manual_reason"),
            "criteria": _safe(criteria),
            "items_detail": item_snapshots,
            "statistics": (
                _safe(scoring.system_statistics(criteria, items))
                if worksheet.get("kind") == "SISTEMAS"
                else None
            ),
        })

    overall_calculated = (
        scoring.audit_summary(summaries, audit.get("manual_score"), thresholds)
        if summaries
        else {"auto": None, "final": None, "rating": "SIN_CALIFICAR"}
    )

    overall = {
        "auto": _number(overall_calculated.get("auto")),
        "final": _number(overall_calculated.get("final")),
        "rating": overall_calculated.get("rating", "SIN_CALIFICAR"),
        "items": sum(int(s.items) for s in summaries),
        "scored": sum(int(s.scored) for s in summaries),
        "exceptions": sum(int(s.exceptions) for s in summaries),
        "manual_override": audit.get("manual_score") is not None,
        "manual_score": _number(audit.get("manual_score")),
        "manual_reason": audit.get("manual_reason"),
    }

    return _safe({
        "audit_code": audit.get("code"),
        "audit_domain": audit.get("audit_domain", "GENERAL"),
        "phase": audit.get("phase"),
        "thresholds": thresholds,
        "overall": overall,
        "worksheets": worksheet_snapshots,
    })
