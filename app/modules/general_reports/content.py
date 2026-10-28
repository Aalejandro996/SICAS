"""Contenido del informe general de auditorías (lógica pura, probada sin base de datos).

Reúne varias auditorías en fase de Documentación o de Informe y, con el motor de reglas, redacta:
introducción, alcance, objetivos, contenido (situación por unidad, resultados por auditoría y hallazgos
por tema normativo con el criterio SUDEASEG del catálogo) y conclusión.

Reglas de la situación de cada unidad (a partir de la calificación promedio y de los hallazgos vigentes):
  CRITICA   3 o más hallazgos de riesgo alto, o calificación < 50 %
  ATENCION  1 o más hallazgos de riesgo alto, o calificación < 70 %
  ACEPTABLE hallazgos de riesgo medio, o calificación < 85 %
  FAVORABLE en otro caso
  SIN_CALIFICAR sin calificación ni hallazgos (la auditoría aún no tiene cédulas respondidas)
"""
from __future__ import annotations

from datetime import date

from app.modules.engagement.regulatory_rules import topic_for

ELIGIBLE_PHASES = ("DOCUMENTACION", "INFORME")
RISKS = ("ALTO", "MEDIO", "BAJO")
SITUATIONS = ("CRITICA", "ATENCION", "ACEPTABLE", "FAVORABLE", "SIN_CALIFICAR")
SITUATION_LABEL = {"CRITICA": "Crítica", "ATENCION": "Requiere atención", "ACEPTABLE": "Aceptable", "FAVORABLE": "Favorable",
                   "SIN_CALIFICAR": "Sin calificar"}
DOMAIN_LABEL = {"FINANCIERA": "auditorías operativas, especiales, administrativas y financieras",
                "SISTEMAS": "auditorías de sistemas y tecnología de la información", "GENERAL": "auditorías"}
PHASE_LABEL = {"DOCUMENTACION": "Documentación", "INFORME": "Informe"}
KIND_LABEL = {"OPERATIVA": "Operativa", "ESPECIAL": "Especial", "ADMINISTRATIVA": "Administrativa", "FINANCIERA": "Financiera"}
MAX_AUDITS = 60


def situation(score: float | None, by_risk: dict) -> str:
    high, medium = by_risk.get("ALTO", 0), by_risk.get("MEDIO", 0)
    if high >= 3 or (score is not None and score < 50):
        return "CRITICA"
    if high >= 1 or (score is not None and score < 70):
        return "ATENCION"
    if medium >= 1 or (score is not None and score < 85):
        return "ACEPTABLE"
    return "FAVORABLE" if score is not None or by_risk.get("BAJO", 0) else "SIN_CALIFICAR"


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return round(sum(values) / len(values), 2) if values else None


def _count(observations):
    return {r: sum(1 for o in observations if o.get("risk") == r) for r in RISKS}


def _pct(v):
    return "sin calificar" if v is None else f"{v:.1f} %"



def _join(words):
    words = [w for w in words if w]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " y " + words[-1] if words else ""


def _cut(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def classify(observation: dict, catalog: list[dict]) -> dict:
    """Tema normativo de un hallazgo según el catálogo (motor de reglas: palabras clave del tema)."""
    return topic_for(catalog, observation.get("title"), observation.get("criteria"), observation.get("condition"))


def build(*, audits: list[dict], catalog: list[dict], company: str, domain: str, title: str, code: str, author: dict,
          filters_text: str, today: date, objective: str | None = None, revision: int = 1) -> dict:
    """Cuerpo del informe. `audits`: auditorías ya leídas con su calificación y sus observaciones vigentes.

    Cada auditoría: id, code, title, unit_name, unit_kind, audit_kind, phase, status, period_from, period_to,
    objectives, scope, score, rating, observations [{title, risk, condition, criteria, recommendation, pac_status}],
    limitations (número de excepciones / información no recibida).
    """
    audits = sorted(audits, key=lambda a: (a["unit_name"], a["code"]))
    domain_label = DOMAIN_LABEL.get(domain, "auditorías")

    # ------------------------------------------------------ resultados por auditoría
    results, topics = [], {}
    for a in audits:
        obs = sorted(a.get("observations") or [], key=lambda o: RISKS.index(o["risk"]) if o.get("risk") in RISKS else 3)
        by_risk = _count(obs)
        results.append({
            "id": a["id"], "code": a["code"], "title": a.get("title") or "", "unit": a["unit_name"], "unit_kind": a.get("unit_kind"),
            "audit_kind": a.get("audit_kind"), "phase": a["phase"], "status": a.get("status"),
            "period": {"from": str(a.get("period_from") or ""), "to": str(a.get("period_to") or "")},
            "score": a.get("score"), "rating": a.get("rating"), "by_risk": by_risk, "limitations": int(a.get("limitations") or 0),
            "situation": situation(a.get("score"), by_risk),
            "observations": [{"title": o["title"], "risk": o.get("risk"), "condition": _cut(o.get("condition"), 600),
                              "recommendation": _cut(o.get("recommendation"), 400), "pac_status": o.get("pac_status"),
                              "topic": classify(o, catalog)["topic"] if catalog else None} for o in obs],
        })
        for o in obs:
            if not catalog:
                break
            t = classify(o, catalog)
            g = topics.setdefault(t["topic"], {"topic": t["topic"], "label": t["label"], "criteria": t["criteria"],
                                               "recommendation": t["recommendation"], "effect": t["effect"],
                                               "by_risk": {r: 0 for r in RISKS}, "units": set(), "audits": set(), "examples": []})
            if o.get("risk") in RISKS:
                g["by_risk"][o["risk"]] += 1
            g["units"].add(a["unit_name"]); g["audits"].add(a["code"])
            if len(g["examples"]) < 4:
                g["examples"].append(f"{a['code']}: {_cut(o['title'], 140)}")

    # ------------------------------------------------------ situación por unidad
    units = {}
    for r in results:
        u = units.setdefault(r["unit"], {"unit": r["unit"], "unit_kind": r["unit_kind"], "audits": [], "scores": [], "by_risk": {k: 0 for k in RISKS}})
        u["audits"].append(r["code"]); u["scores"].append(r["score"])
        for k in RISKS:
            u["by_risk"][k] += r["by_risk"][k]
    unit_rows = []
    for u in units.values():
        score = _avg(u["scores"])
        unit_rows.append({"unit": u["unit"], "unit_kind": u["unit_kind"], "audits": u["audits"], "score": score,
                          "by_risk": u["by_risk"], "situation": situation(score, u["by_risk"])})
    unit_rows.sort(key=lambda u: (SITUATIONS.index(u["situation"]), u["score"] if u["score"] is not None else 101, u["unit"]))

    topic_rows = sorted(({**g, "units": sorted(g["units"]), "audits": sorted(g["audits"]), "total": sum(g["by_risk"].values())}
                         for g in topics.values()),
                        key=lambda g: (-g["by_risk"]["ALTO"], -g["total"], g["label"]))

    # ------------------------------------------------------ indicadores
    total = _count([o for r in results for o in r["observations"]])
    overall = _avg(r["score"] for r in results)
    by_situation = {s: sum(1 for u in unit_rows if u["situation"] == s) for s in SITUATIONS}
    periods = [p for r in results for p in (r["period"]["from"], r["period"]["to"]) if p]
    period = {"from": min(periods) if periods else "", "to": max(periods) if periods else ""}
    kpis = {"audits": len(results), "units": len(unit_rows), "avg_score": overall, "observations": sum(total.values()),
            "by_risk": total, "by_situation": by_situation, "limitations": sum(r["limitations"] for r in results),
            "pac_open": sum(1 for r in results for o in r["observations"] if o.get("pac_status") in ("PENDIENTE", "EN_CURSO"))}

    # ------------------------------------------------------ textos del motor de reglas
    n_units, n_audits = len(unit_rows), len(results)
    kinds = sorted({KIND_LABEL.get(r["audit_kind"], r["audit_kind"]) for r in results if r["audit_kind"]})
    phases = sorted({PHASE_LABEL.get(r["phase"], r["phase"]) for r in results})
    introduction = (
        f"La Contraloría Corporativa de {company}, a través de su equipo de auditoría, presenta el informe general {code} "
        f"sobre {n_audits} {domain_label} practicadas a {n_units} unidad(es) y/o sucursal(es) que se encuentran en fase de "
        f"{_join(phases).lower()}. El informe consolida la calificación de cada auditoría, los hallazgos vigentes y su "
        f"tratamiento normativo, con el fin de presentar a la Gerencia y a la Contraloría el estado actual de la "
        f"organización en las unidades evaluadas, tomando en cuenta las disposiciones de la Superintendencia de la "
        f"Actividad Aseguradora (SUDEASEG) y la normativa interna aplicable.")
    scope = (
        f"Comprende {n_audits} auditoría(s){' de tipo ' + _join(kinds).lower() if kinds else ''} en fase de "
        f"{_join(phases).lower()}, con períodos revisados entre {period['from'] or '—'} y {period['to'] or '—'}. "
        f"Criterio de selección: {filters_text}. Se consideran las cédulas de trabajo, las calificaciones y los hallazgos "
        f"vigentes registrados en SICAS a la fecha de emisión; las auditorías que aún no cierran su fase pueden variar.")
    objectives = [objective] if objective else []
    objectives += [
        "Presentar el estado actual de control interno de las unidades y sucursales evaluadas.",
        "Consolidar las calificaciones y los hallazgos de las auditorías seleccionadas, con su nivel de riesgo.",
        "Relacionar los hallazgos con los requisitos normativos de la SUDEASEG y la normativa interna aplicable.",
        "Identificar las unidades y los temas que requieren acción prioritaria de la Gerencia.",
    ]

    critical = [u["unit"] for u in unit_rows if u["situation"] == "CRITICA"]
    attention = [u["unit"] for u in unit_rows if u["situation"] == "ATENCION"]
    top = [t for t in topic_rows if t["total"]][:3]
    general = ("desfavorable" if by_situation["CRITICA"] else "con debilidades que requieren atención" if by_situation["ATENCION"]
               else "aceptable" if by_situation["ACEPTABLE"] else "favorable" if by_situation["FAVORABLE"]
               else "aún no determinable (auditorías sin calificar)")
    conclusion = [
        f"La situación general de control interno en las unidades evaluadas es {general}: "
        f"{'calificación promedio de ' + _pct(overall) if overall is not None else 'sin calificación registrada'}, con {kpis['observations']} hallazgo(s) vigente(s) ({total['ALTO']} de riesgo alto, {total['MEDIO']} medio "
        f"y {total['BAJO']} bajo)."]
    if critical:
        conclusion.append(f"Situación crítica en {_join(critical)}: se recomienda priorizar sus planes de acción y su seguimiento.")
    if attention:
        conclusion.append(f"Requieren atención: {_join(attention)}.")
    if top:
        conclusion.append("Los temas normativos con más hallazgos son " + _join(f"{t['label']} ({t['total']})" for t in top)
                          + "; su incumplimiento expone a la organización ante la SUDEASEG.")
    if kpis["limitations"]:
        conclusion.append(f"Se registraron {kpis['limitations']} limitación(es) al alcance por información no recibida.")
    if not kpis["observations"]:
        conclusion.append("No se registran hallazgos vigentes en las auditorías consolidadas.")
    recommendations = [f"{t['label'].capitalize()}: {t['recommendation']}" for t in top]

    return {
        "kind": "GENERAL", "code": code, "title": title, "company": company, "domain": domain, "revision": revision,
        "generated_on": today.isoformat(), "author": author, "filters": filters_text,
        "introduction": introduction, "scope": scope, "objectives": objectives, "period": period,
        "kpis": kpis, "units": unit_rows, "audits": results, "topics": topic_rows,
        "conclusion": conclusion, "recommendations": recommendations,
    }
