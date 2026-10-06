"""Une los datos ya leídos de la base y arma el cuerpo del informe (lógica pura, probada sin base de datos)."""
from __future__ import annotations

from datetime import date

from . import scoring
from .report_builder import build_body
from .templates import KINDS, LINES


def sheet_title(ws: dict) -> str:
    return f"{KINDS[ws['kind']]} — {LINES[ws['line']]}"


def summarize_sheets(worksheets: list[dict], thresholds: dict | None) -> list[tuple[dict, scoring.SheetSummary]]:
    return [(ws, scoring.worksheet_summary(ws["criteria"], ws["items"], ws.get("manual_score"), thresholds)) for ws in worksheets]   # Decimal -> float dentro de scoring


def assemble(*, kind: str, audit: dict, file: dict, unit: dict, team: list[dict], worksheets: list[dict], observations: list[dict],
             evidence: list[dict], thresholds: dict | None, company: str, version: int, today: date, conclusion: str | None = None) -> dict:
    pairs = summarize_sheets(worksheets, thresholds)
    sheets = [{"title": sheet_title(ws), "kind": ws["kind"], "line": ws["line"], "items": s.items, "scored": s.scored, "exceptions": s.exceptions,
               "auto": s.auto, "final": s.final, "manual_override": s.manual_override, "rating": s.rating} for ws, s in pairs]
    overall = scoring.audit_summary([s for _, s in pairs], audit.get("manual_score"), thresholds)
    limitations, adjustments = [], []
    for ws in worksheets:
        for it in ws["items"]:
            res = it.get("results") or {}
            if it.get("info_exception") or "EXCEPCION" in res.values():
                limitations.append({"sheet": sheet_title(ws), "ref": it["ref"], "detail": it.get("info_exception") or "Información no recibida (sin detalle)"})
            if it.get("manual_score") is not None:
                auto = scoring.item_score(ws["criteria"], res)
                adjustments.append({"sheet": sheet_title(ws), "ref": it["ref"], "auto": auto, "final": float(it["manual_score"]), "reason": it.get("manual_reason") or ""})
        if ws.get("manual_score") is not None:
            adjustments.append({"sheet": sheet_title(ws), "ref": "(toda la cédula)", "auto": scoring.worksheet_summary(ws["criteria"], ws["items"], None, thresholds).auto,
                                "final": float(ws["manual_score"]), "reason": ws.get("manual_reason") or ""})
    obs = [{"n": o["seq"], "title": o["title"], "condition": o["condition"], "criteria": o.get("criteria") or "", "cause": o.get("cause") or "",
            "effect": o.get("effect") or "", "recommendation": o.get("recommendation") or "", "risk": o["risk"],
            "unit_decision": o.get("unit_decision"), "unit_response": o.get("unit_response") or "", "pac_action": o.get("pac_action") or "",
            "pac_owner": o.get("pac_owner") or "", "pac_due": str(o["pac_due"]) if o.get("pac_due") else ""} for o in sorted(observations, key=lambda x: x["seq"])]
    ev = [{"n": i, "filename": e["filename"], "description": e.get("description") or "", "sha256": e["sha256"]} for i, e in enumerate(evidence, 1)]
    body = build_body(kind=kind, audit=audit, file=file, unit=unit, team=team, sheets=sheets, overall=overall, observations=obs,
                      limitations=limitations, adjustments=adjustments, evidence=ev, company=company, version=version, today=today,
                      conclusion=conclusion, thresholds=thresholds)
    if audit.get("manual_score") is not None:
        body["overall_reason"] = audit.get("manual_reason") or ""
    return body
