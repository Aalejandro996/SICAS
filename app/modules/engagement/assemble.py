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
             evidence: list[dict], thresholds: dict | None, company: str, version: int, today: date, conclusion: str | None = None,
             history: dict | None = None, revision: int = 1) -> dict:
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
    body["revision"] = revision
    body["comparison"] = scoring.comparison(
        [{**ws, "title": sheet_title(ws)} for ws in worksheets], overall, thresholds)
    if history is not None:
        body.update(trace_sections(history, observations, evidence))
    return body


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


TRIGGER_LABEL = {"PHASE_CHANGE": "Cierre de fase", "FINAL_REPORT_SUBMITTED": "Envío del informe final", "PAC_SENT": "Envío del PAC"}
ACTION_LABEL = {"SUBMIT": "Envío a revisión", "RETURN": "Devolución", "APPROVE_JEFE": "Aprobación del Jefe de Auditoría",
                "APPROVE_SIGN_GERENTE": "Aprobación y firma de Gerencia", "APPROVE_SIGN_CONTRALOR": "Aprobación y firma de Contraloría",
                "SEND_PREVIO": "Envío del informe previo"}


def trace_sections(history: dict, observations: list[dict], evidence: list[dict]) -> dict:
    """Secciones de trazabilidad del informe final (datos ya leídos; lógica pura)."""
    ev_n = {e.get("sha256"): i for i, e in enumerate(evidence, 1)}
    score_history = []
    for snap in history.get("snapshots") or []:
        card, var = snap.get("scorecard") or {}, snap.get("variation") or {}
        ov = card.get("overall") or {}
        score_history.append({
            "phase": snap.get("phase"), "event": TRIGGER_LABEL.get(snap.get("trigger_action"), snap.get("trigger_action")),
            "date": _iso(snap.get("captured_at")), "user": snap.get("captured_username"),
            "score": ov.get("final"), "rating": ov.get("rating"), "delta": var.get("overall_delta"),
            "reason": card.get("reason"), "rule_version": card.get("rule_version"),
            "report_version": snap.get("report_version"),
            "changed_items": [{"sheet": i.get("sheet"), "ref": i.get("ref"), "before": i.get("before"), "after": i.get("after"),
                               "delta": i.get("delta"),
                               "reason": i.get("manual_reason") or i.get("info_exception") or i.get("observation") or ""}
                              for i in (var.get("items") or [])][:50],
            "evidence_added": [{"n": ev_n.get(e.get("sha256")), "filename": e.get("filename")} for e in (var.get("evidence_added") or [])],
        })

    revs: dict[str, list[dict]] = {}
    for r in history.get("observation_revisions") or []:
        revs.setdefault(r["observation_id"], []).append(r)
    obs_trace = []
    for o in sorted(observations, key=lambda x: x["seq"]):
        rows = revs.get(o["id"]) or []
        if len(rows) <= 1:
            continue
        first = rows[0].get("data") or {}
        obs_trace.append({
            "n": o["seq"], "title": o["title"],
            "original": {k: first.get(k) for k in ("title", "condition", "risk")},
            "changes": [{"revision": r["revision"], "date": _iso(r.get("created_at")), "user": r.get("username"),
                         "fields": r.get("changed_fields") or [], "reason": r.get("reason") or ""} for r in rows[1:]],
        })

    points = history.get("review_points") or []
    review = [{"date": _iso(t.get("created_at")), "action": ACTION_LABEL.get(t["action"], t["action"]), "code": t["action"],
               "report_version": t.get("report_version"), "from": t.get("from_status"), "to": t.get("to_status"),
               "user": t.get("actor_username"), "comment": t.get("comment") or "",
               "points": [{"id": p.get("id"), "target": p.get("target_label") or "General", "description": p["description"], "status": p["status"],
                           "attended_note": p.get("attended_note") or ""}
                          for p in points if p.get("transition_id") == t.get("id")]}
              for t in history.get("transitions") or [] if t.get("kind", "FINAL") == "FINAL"]
    return {
        "score_history": score_history,
        "observation_changes": obs_trace,
        "review_history": review,
        "review_points_pending": sum(1 for p in points if p["status"] == "PENDIENTE"),
        "reopenings": [{"version": r["version"], "reason": r["reason"], "date": _iso(r.get("authorized_at")), "user": r.get("username")}
                       for r in history.get("reopenings") or []],
    }
