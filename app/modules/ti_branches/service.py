"""Resultados de la Evaluación TI de las sucursales, consolidados al cerrar cada auditoría operativa.

Este módulo solo lee la tabla engagement.ti_branch_results: no modifica auditorías ni influye en otras evaluaciones.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text

from app.extensions import db
from app.modules.engagement import ti_branch

CRITICALITY_LABEL = {"CRITICA": "Crítica", "ALTA": "Alta", "MEDIA": "Media", "BAJA": "Baja"}
LEVEL_CRITICALITY = {4: "CRITICA", 3: "ALTA", 2: "MEDIA", 1: "BAJA"}


def _rows(sql, **p):
    return [dict(r._mapping) for r in db.session.execute(text(sql), p).all()]


def publish(audit_id) -> bool:
    """Guarda el consolidado de la Evaluación TI de una auditoría cerrada. Devuelve False si no la tiene."""
    sheets = _rows("SELECT w.id::text, w.criteria FROM engagement.worksheets w WHERE w.audit_id = CAST(:a AS uuid) AND w.kind = 'TI_SUC'",
                   a=str(audit_id))
    if not sheets:
        return False
    from app.modules.engagement import repositories as repo
    criteria, items = None, []
    for s in sheets:
        ws = repo.get_worksheet(s["id"])
        criteria = criteria or ws["criteria"]
        items += ws["items"]
    s = ti_branch.summary(criteria, items)
    if not s["rated"]:
        return False
    head = _rows("SELECT a.code AS audit_code, f.unit_id, u.code AS unit_code, u.name AS unit_name, f.period_from, f.period_to, "
                 "COALESCE(a.pac_sent_at, now()) AS closed_at FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id "
                 "JOIN engagement.units u ON u.id = f.unit_id WHERE a.id = CAST(:a AS uuid)", a=str(audit_id))[0]
    detail = {"people": [{k: p[k] for k in ("name", "role", "yes", "score", "final", "level", "risk", "sod", "dictamen", "complete")}
                         | {"answers": {c["code"]: ti_branch.answer(it.get("results") or {}, c["code"]) for c in criteria},
                            "comments": {k: v.get("c") for k, v in (it.get("results") or {}).items() if isinstance(v, dict) and v.get("c")}}
                         for p, it in zip(s["people"], items)],
              "questions": s["questions"], "avg_yes": s["avg_yes"], "level_label": s["level_label"], "criticality": s["criticality"]}
    db.session.execute(text(
        "INSERT INTO engagement.ti_branch_results (audit_id, unit_id, unit_code, unit_name, audit_code, period_from, period_to, closed_at, "
        "collaborators, score, module1_pct, level, risk, sod_conflicts, dictamen, detail) VALUES (CAST(:a AS uuid), :unit_id, :unit_code, "
        ":unit_name, :audit_code, :period_from, :period_to, :closed_at, :n, :score, :m1, :level, :risk, :sod, :dict, CAST(:detail AS jsonb)) "
        "ON CONFLICT (audit_id) DO UPDATE SET collaborators = EXCLUDED.collaborators, score = EXCLUDED.score, module1_pct = EXCLUDED.module1_pct, "
        "level = EXCLUDED.level, risk = EXCLUDED.risk, sod_conflicts = EXCLUDED.sod_conflicts, dictamen = EXCLUDED.dictamen, "
        "detail = EXCLUDED.detail, closed_at = EXCLUDED.closed_at"),
        {**head, "a": str(audit_id), "n": s["rated"], "score": s["score"], "m1": s["module1_pct"], "level": s["level"], "risk": s["risk"],
         "sod": s["sod_conflicts"], "dict": s["dictamen"], "detail": json.dumps(detail, default=str)})
    db.session.commit()
    return True


def search(date_from: date | None = None, date_to: date | None = None, unit_id: int | None = None, criticality: str | None = None,
           sod: str | None = None, latest: bool = True) -> dict:
    """Evaluaciones filtradas, indicadores y preguntas más incumplidas."""
    rows = _rows(
        "SELECT r.audit_id::text, r.unit_id, r.unit_code, r.unit_name, r.audit_code, r.period_from, r.period_to, r.closed_at, r.collaborators, "
        "r.score::float AS score, r.module1_pct::float AS module1_pct, r.level, r.risk, r.sod_conflicts, r.dictamen, r.detail, "
        "row_number() OVER (PARTITION BY r.unit_id ORDER BY r.closed_at DESC) AS rn "
        "FROM engagement.ti_branch_results r WHERE (CAST(:df AS date) IS NULL OR r.closed_at::date >= CAST(:df AS date)) "
        "AND (CAST(:dt AS date) IS NULL OR r.closed_at::date <= CAST(:dt AS date)) AND (CAST(:u AS int) IS NULL OR r.unit_id = CAST(:u AS int)) "
        "ORDER BY r.closed_at DESC", df=date_from, dt=date_to, u=unit_id)
    if latest:
        rows = [r for r in rows if r["rn"] == 1]
    for r in rows:
        r["criticality"] = LEVEL_CRITICALITY.get(r["level"])
    if criticality:
        rows = [r for r in rows if r["criticality"] == criticality]
    if sod == "SI":
        rows = [r for r in rows if r["sod_conflicts"]]
    elif sod == "NO":
        rows = [r for r in rows if not r["sod_conflicts"]]
    questions: dict[str, dict] = {}
    for r in rows:
        for q in (r["detail"] or {}).get("questions", []):
            acc = questions.setdefault(q["code"], {k: q[k] for k in ("code", "number", "module", "topic", "text", "iso", "cobit")} | {"failed": 0, "answered": 0})
            acc["failed"] += q["failed"]
            acc["answered"] += q["yes"] + q["no"]
    for q in questions.values():
        q["fail_rate"] = round(q["failed"] / q["answered"] * 100, 2) if q["answered"] else None
    scores = [r["score"] for r in rows if r["score"] is not None]
    kpis = {"branches": len({r["unit_id"] for r in rows}), "evaluations": len(rows), "collaborators": sum(r["collaborators"] for r in rows),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            "by_criticality": {k: sum(1 for r in rows if r["criticality"] == k) for k in ("CRITICA", "ALTA", "MEDIA", "BAJA")},
            "with_sod": sum(1 for r in rows if r["sod_conflicts"]), "sod_people": sum(r["sod_conflicts"] for r in rows)}
    for r in rows:
        r.pop("detail", None)
        r.pop("rn", None)
    return {"rows": rows, "kpis": kpis,
            "questions": sorted(questions.values(), key=lambda q: (-(q["fail_rate"] or 0), q["code"]))}


def detail(audit_id) -> dict | None:
    rows = _rows("SELECT audit_id::text, unit_id, unit_code, unit_name, audit_code, period_from, period_to, closed_at, collaborators, "
                 "score::float AS score, module1_pct::float AS module1_pct, level, risk, sod_conflicts, dictamen, detail "
                 "FROM engagement.ti_branch_results WHERE audit_id = CAST(:a AS uuid)", a=str(audit_id))
    if not rows:
        return None
    r = rows[0]
    r["criticality"] = LEVEL_CRITICALITY.get(r["level"])
    r["history"] = _rows("SELECT audit_id::text, audit_code, closed_at, score::float AS score, level, sod_conflicts FROM engagement.ti_branch_results "
                         "WHERE unit_id = :u ORDER BY closed_at", u=r["unit_id"])
    return r


def branches() -> list[dict]:
    return _rows("SELECT DISTINCT unit_id, unit_name FROM engagement.ti_branch_results ORDER BY unit_name")


def sudeaseg_reference() -> str:
    rows = _rows("SELECT criteria FROM engagement.regulatory_catalog WHERE topic = 'tecnologia_sucursal' AND active")
    return rows[0]["criteria"] if rows else "Normativa de la SUDEASEG aplicable a la seguridad de la información y la tecnología."
