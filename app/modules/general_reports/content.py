"""Contenido de los informes consolidados de auditorías (lógica pura, probada sin base de datos).

Informe Ejecutivo (ambos dominios): auditorías CERRADAS en un trimestre, semestre o año, según su fecha de
cierre. Con el motor de reglas redacta introducción, objetivos, alcance, contenido (situación por unidad,
resultados por auditoría con un párrafo breve y el cuadro de hallazgos con su nivel de riesgo, y hallazgos por
tema normativo con el criterio SUDEASEG del catálogo) y conclusión.

Informe de Documentación (Sistemas): auditorías en fase de Documentación y lo obtenido de cada control
pedido en la carta de solicitud (recibido actualizado o desactualizado, no entregado o sin respuesta).

Reglas de la situación de cada unidad (a partir de la calificación promedio y de los hallazgos vigentes):
  CRITICA   3 o más hallazgos de riesgo alto, o calificación < 50 %
  ATENCION  1 o más hallazgos de riesgo alto, o calificación < 70 %
  ACEPTABLE hallazgos de riesgo medio, o calificación < 85 %
  FAVORABLE en otro caso
  SIN_CALIFICAR sin calificación ni hallazgos (la auditoría aún no tiene cédulas respondidas)
"""
from __future__ import annotations

from datetime import date

from app.modules.engagement import conclusions as cc
from app.modules.engagement.regulatory_rules import topic_for

REPORT_KINDS = {"EJECUTIVO": "Informe Ejecutivo", "DOCUMENTACION": "Informe de Documentación"}
PERIOD_TYPES = {"TRIMESTRE": 4, "SEMESTRE": 2, "ANUAL": 1}
ORDINAL = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto"}
DOC_ORDER = ("ACTUALIZADA", "DESACTUALIZADA", "NO_ENTREGADA", "SIN_RESPUESTA")
RISKS = ("ALTO", "MEDIO", "BAJO")
SITUATIONS = ("CRITICA", "ATENCION", "ACEPTABLE", "FAVORABLE", "SIN_CALIFICAR")
SITUATION_LABEL = {"CRITICA": "Crítica", "ATENCION": "Requiere atención", "ACEPTABLE": "Aceptable", "FAVORABLE": "Favorable",
                   "SIN_CALIFICAR": "Sin calificar"}
DOMAIN_LABEL = {"FINANCIERA": "auditorías operativas, especiales, administrativas y financieras",
                "SISTEMAS": "auditorías de sistemas y tecnología de la información", "GENERAL": "auditorías"}
PHASE_LABEL = {"DOCUMENTACION": "Documentación", "INFORME": "Informe", "LEVANTAMIENTO": "Levantamiento",
               "PRUEBAS_CAMPO": "Pruebas de campo", "PLANIFICACION": "Planificación", "TRABAJO_CAMPO": "Trabajo de campo"}
KIND_LABEL = {"OPERATIVA": "Operativa", "ESPECIAL": "Especial", "ADMINISTRATIVA": "Administrativa", "FINANCIERA": "Financiera"}
MAX_AUDITS = 60


def period_range(ptype: str, n: int, year: int) -> tuple[date, date, str]:
    """(inicio, fin exclusivo, etiqueta) del trimestre, semestre o año."""
    if ptype not in PERIOD_TYPES or not 1 <= n <= PERIOD_TYPES[ptype] or not 2000 <= year <= 2100:
        raise ValueError("Período inválido: trimestre 1 a 4, semestre 1 o 2, o año")
    months = 12 // PERIOD_TYPES[ptype]
    start = date(year, (n - 1) * months + 1, 1)
    end = date(year + 1, 1, 1) if n * months == 12 else date(year, n * months + 1, 1)
    label = (f"año {year}" if ptype == "ANUAL" else f"{ORDINAL[n]} {ptype.lower()} de {year}")
    return start, end, label


situation = cc.situation


def previous_period(ptype: str, n: int, year: int) -> tuple[str, int, int]:
    """Período anterior del mismo tipo (para la tendencia del Informe Ejecutivo)."""
    if ptype == "ANUAL":
        return ptype, 1, year - 1
    return (ptype, n - 1, year) if n > 1 else (ptype, PERIOD_TYPES[ptype], year - 1)


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


def _dmy(v) -> str:
    v = str(v or "")[:10]
    return f"{v[8:10]}/{v[5:7]}/{v[:4]}" if len(v) == 10 else "—"


def overdue(o: dict, today: date) -> bool:
    """Plan de acción vencido: fecha comprometida pasada y no cumplido."""
    due = str(o.get("pac_due") or "")[:10]
    return bool(due) and due < today.isoformat() and o.get("pac_status") != "CUMPLIDA"


def audit_summary(a: dict, by_risk: dict, today: date | None = None) -> str:
    """Párrafo breve de una auditoría para el Informe Ejecutivo, según su tipo, con la comparación con la anterior."""
    obs = a.get("observations") or []
    n = sum(by_risk.values())
    score = a.get("score")
    kind = cc.kind_label(a.get("audit_kind"), a.get("audit_domain"))
    head = (f"Auditoría {kind + ' ' if kind else ''}practicada a {a['unit_name']}"
            + (f", cerrada el {_dmy(a.get('closed_at'))}" if a.get("closed_at") else "")
            + (f" (período revisado del {_dmy(a.get('period_from'))} al {_dmy(a.get('period_to'))})" if a.get("period_from") else "") + ". ")
    grade = (f"Obtuvo una calificación de {_pct(score)}" if score is not None else "No registra calificación")
    text = head + grade + (f" con {n} hallazgo(s): {by_risk['ALTO']} de riesgo alto, {by_risk['MEDIO']} medio y {by_risk['BAJO']} bajo."
                           if n else " y no presenta hallazgos vigentes.")
    topics = cc.topic_counts(obs)
    if topics:
        text += f" El tema principal es {topics[0]['label']} ({topics[0]['total']})."
    lcft = a.get("lcft")
    if lcft and lcft.get("index") is not None:
        text += f" Prevención LC/FT/FPADM: índice {_pct(lcft['index'])}" + (f", bloques que no cumplen: {_join(lcft['critical'][:2])}." if lcft.get("critical") else ".")
    prev = a.get("previous")
    if prev:
        trend = cc.trend_sentence(score, prev)
        rep = cc.repeated_topics(obs, prev)
        text += f" Frente a la auditoría anterior ({prev['code']})" + (f": {trend[0].lower() + trend[1:]}" if trend else "") + "."
        if rep:
            text += f" Se repiten hallazgos en {_join(rep[:2])}."
    elif "previous" in a:
        text += " Es la primera auditoría de la unidad registrada en SICAS."
    if n:
        done = sum(1 for o in obs if o.get("pac_status") == "CUMPLIDA")
        late = sum(1 for o in obs if overdue(o, today or date.today()))
        text += f" Plan de acción: {done} de {n} cumplido(s)" + (f", {late} vencido(s)." if late else ".")
    if by_risk["ALTO"]:
        text += " Los hallazgos de riesgo alto requieren acción prioritaria."
    return text


def lcft_section(results: list[dict], topic_rows: list[dict]) -> dict:
    """Cumplimiento LC/FT/FPADM: índice del cuestionario de prevención de cada auditoría y hallazgos de los temas LC/FT."""
    audits = [{"code": r["code"], "unit": r["unit"], **r["lcft"]} for r in results if r.get("lcft") and r["lcft"].get("index") is not None]
    topics = [t for t in topic_rows if cc.is_lcft_topic(t["topic"]) and t["total"]]
    findings = sum(t["total"] for t in topics)
    high = sum(t["by_risk"]["ALTO"] for t in topics)
    if not audits and not findings:
        return {"audits": [], "topics": [], "findings": 0, "text": ""}
    parts = []
    if audits:
        avg = _avg(a["index"] for a in audits)
        weak = [f"{a['unit']} ({_pct(a['index'])})" for a in audits if a.get("risk") in ("ALTO", "MEDIO")]
        parts.append(f"el índice promedio de cumplimiento es {_pct(avg)} en {len(audits)} auditoría(s)"
                     + (f" (con riesgo medio o alto: {_join(weak[:4])})" if weak else ""))
    if findings:
        parts.append(f"{findings} hallazgo(s) de prevención ({high} de riesgo alto), principalmente en "
                     + _join(t["label"] for t in topics[:2]))
    text = "Prevención de LC/FT/FPADM (Providencia SUDEASEG SAA-01-0536-2024): " + "; ".join(parts) + (". El incumplimiento expone a la empresa a sanciones de la SUDEASEG y a responsabilidad penal; "
                               "debe informarse al Oficial de Cumplimiento." if high or any(a.get("risk") == "ALTO" for a in audits) else ".")
    return {"audits": audits, "topics": [{"topic": t["topic"], "label": t["label"], "total": t["total"], "by_risk": t["by_risk"],
                                          "units": t["units"]} for t in topics], "findings": findings, "text": text}


def build(*, audits: list[dict], catalog: list[dict], company: str, domain: str, title: str, code: str, author: dict,
          filters_text: str, today: date, objective: str | None = None, revision: int = 1, period_label: str = "",
          previous_period: dict | None = None) -> dict:
    """Cuerpo del informe. `audits`: auditorías ya leídas con su calificación y sus observaciones vigentes.

    Cada auditoría: id, code, title, unit_name, unit_kind, audit_kind, phase, status, period_from, period_to,
    objectives, scope, score, rating, observations [{title, risk, condition, criteria, recommendation, pac_status}],
    limitations (número de excepciones / información no recibida); opcionales: previous (auditoría anterior de la
    unidad), lcft (índice del cuestionario de prevención LC/FT/FPADM). Las observaciones pueden traer su tema ya
    clasificado (topic, topic_label). `previous_period`: {label, audits, avg_score, by_risk} del período anterior.
    """
    by_key = {c["topic"]: c for c in catalog or []}
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
            "situation": situation(a.get("score"), by_risk), "closed_at": str(a.get("closed_at") or "")[:10],
            "summary": audit_summary(a, by_risk, today), "previous": a.get("previous"), "lcft": a.get("lcft"),
            "observations": [{"title": _cut(o["title"], 240), "risk": o.get("risk"), "pac_status": o.get("pac_status"),
                              "pac_due": str(o.get("pac_due") or "")[:10] or None, "overdue": overdue(o, today),
                              "topic": o.get("topic") or (classify(o, catalog)["topic"] if catalog else None)} for o in obs],
        })
        for o in obs:
            if not catalog:
                break
            t = by_key.get(o.get("topic")) or classify(o, catalog)
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
            "pac_open": sum(1 for r in results for o in r["observations"] if o.get("pac_status") in ("PENDIENTE", "EN_CURSO")),
            "pac_overdue": sum(1 for r in results for o in r["observations"] if o["overdue"])}

    # ------------------------------------------------------ textos del motor de reglas
    n_units, n_audits = len(unit_rows), len(results)
    kinds = sorted({KIND_LABEL.get(r["audit_kind"], r["audit_kind"]) for r in results if r["audit_kind"]})
    introduction = (
        f"La Contraloría Corporativa de {company}, a través de su equipo de auditoría, presenta el Informe Ejecutivo {code} "
        f"del {period_label}: {n_audits} auditoría(s) cerrada(s) en el período ({domain_label}), practicadas a {n_units} "
        f"unidad(es) y/o sucursal(es). El informe resume la calificación de cada auditoría, sus hallazgos con el nivel de riesgo que "
        f"representan y su tratamiento normativo, para presentar a la Gerencia y a la Contraloría el estado de la "
        f"organización en las unidades evaluadas, tomando en cuenta las disposiciones de la Superintendencia de la "
        f"Actividad Aseguradora (SUDEASEG) y la normativa interna aplicable.")
    scope = (
        f"Comprende las auditorías{' de tipo ' + _join(kinds).lower() if kinds else ''} cerradas (finalizadas) en el "
        f"{period_label}, con períodos revisados entre {_dmy(period['from'])} y {_dmy(period['to'])}. "
        f"Criterio de selección: {filters_text}. Se consideran las calificaciones y los hallazgos vigentes registrados en "
        f"SICAS a la fecha de emisión.")
    objectives = [objective] if objective else []
    objectives += [
        f"Presentar el resultado de las auditorías cerradas en el {period_label} y el estado de control interno de las unidades evaluadas.",
        "Resumir los hallazgos de cada auditoría con el nivel de riesgo que representan.",
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
    if previous_period and previous_period.get("audits"):
        pp = previous_period
        trend = cc.trend_sentence(overall, {"score": pp.get("avg_score")}, "la calificación promedio")
        conclusion.append(f"Frente al {pp['label']} ({pp['audits']} auditoría(s) cerrada(s)): "
                          + (trend[0].lower() + trend[1:] + "; " if trend else "")
                          + f"los hallazgos de riesgo alto pasaron de {pp['by_risk'].get('ALTO', 0)} a {total['ALTO']}.")
    elif previous_period is not None:
        conclusion.append(f"No hay auditorías cerradas en el {previous_period['label']} para comparar la tendencia.")
    if critical:
        conclusion.append(f"Situación crítica en {_join(critical)}: se recomienda priorizar sus planes de acción y su seguimiento.")
    if attention:
        conclusion.append(f"Requieren atención: {_join(attention)}.")
    if top:
        conclusion.append("Los temas normativos con más hallazgos son " + _join(f"{t['label']} ({t['total']})" for t in top)
                          + "; su incumplimiento expone a la organización ante la SUDEASEG.")
    spread = [t for t in topic_rows if len(t["units"]) >= 2]
    if spread:
        conclusion.append("Se repiten en varias unidades: " + _join(f"{t['label']} ({_join(t['units'][:3])})" for t in spread[:3])
                          + "; la causa es transversal y requiere una acción corporativa, no solo de cada unidad.")
    recurrent = [r["code"] for r in results if r.get("previous") and cc.repeated_topics(
        [{"topic": o["topic"], "label": o["topic"], "risk": o["risk"]} for o in r["observations"]], r["previous"])]
    if recurrent:
        conclusion.append(f"En {len(recurrent)} auditoría(s) ({_join(recurrent[:4])}) se repiten temas de la auditoría anterior de la unidad: "
                          "las acciones correctivas previas no fueron efectivas.")
    if kpis["pac_overdue"]:
        late_units = sorted({r["unit"] for r in results for o in r["observations"] if o["overdue"]})
        conclusion.append(f"Hay {kpis['pac_overdue']} plan(es) de acción vencido(s) sin cumplir, en {_join(late_units[:4])}: "
                          "deben escalarse a la Gerencia responsable.")
    lcft = lcft_section(results, topic_rows)
    if lcft["text"]:
        conclusion.append(lcft["text"])
    if kpis["limitations"]:
        conclusion.append(f"Se registraron {kpis['limitations']} limitación(es) al alcance por información no recibida.")
    if not kpis["observations"]:
        conclusion.append("No se registran hallazgos vigentes en las auditorías consolidadas.")
    recommendations = [f"{t['label'][:1].upper() + t['label'][1:]}: {t['recommendation']}" for t in top]

    return {
        "kind": "EJECUTIVO", "code": code, "title": title, "company": company, "domain": domain, "revision": revision,
        "generated_on": today.isoformat(), "author": author, "filters": filters_text, "period_label": period_label,
        "introduction": introduction, "scope": scope, "objectives": objectives, "period": period,
        "kpis": kpis, "units": unit_rows, "audits": results, "topics": topic_rows, "lcft": lcft,
        "previous_period": previous_period, "conclusion": conclusion, "conclusion_auto": list(conclusion), "conclusion_custom": False,
        "recommendations": recommendations,
    }


def build_documentation(*, audits: list[dict], company: str, title: str, code: str, author: dict, filters_text: str,
                        today: date, objective: str | None = None, revision: int = 1) -> dict:
    """Informe de Documentación (Sistemas): lo obtenido de cada control pedido en la carta de solicitud.

    Cada auditoría: id, code, title, unit_name, phase, period_from, period_to,
    letter [{ref, question, status, note, documents, domain, critical}].
    Techo de Pruebas de campo: los controles de la carta sin documentación valen 0, así que la nota de esos controles
    no puede superar el porcentaje de documentación obtenida.
    """
    audits = sorted(audits, key=lambda a: (a["unit_name"], a["code"]))
    rows, totals = [], {k: 0 for k in (*DOC_ORDER, "PENDIENTE")}
    for a in audits:
        counts = {k: 0 for k in (*DOC_ORDER, "PENDIENTE")}
        for c in a.get("letter") or []:
            counts[c["status"] if c["status"] in DOC_ORDER else "PENDIENTE"] += 1
        requested = sum(counts.values())
        received = counts["ACTUALIZADA"] + counts["DESACTUALIZADA"]
        for k in counts:
            totals[k] += counts[k]
        rate = round(received / requested * 100, 2) if requested else None
        missing = counts["NO_ENTREGADA"] + counts["SIN_RESPUESTA"]
        critical_missing = [{"ref": c["ref"], "question": _cut(c["question"], 160), "domain": c.get("domain") or ""}
                            for c in a.get("letter") or [] if c.get("critical") and c["status"] in ("NO_ENTREGADA", "SIN_RESPUESTA")]
        summary = (f"Auditoría practicada a {a['unit_name']}: la carta pidió la documentación de {requested} control(es); "
                   f"se recibió la de {received} ({counts['ACTUALIZADA']} actualizada y {counts['DESACTUALIZADA']} desactualizada)"
                   + (f", {counts['NO_ENTREGADA']} no la tienen o no la entregaron y {counts['SIN_RESPUESTA']} quedaron sin respuesta" if missing else "")
                   + (f"; {counts['PENDIENTE']} aún sin registrar" if counts["PENDIENTE"] else "") + "."
                   + (f" En Pruebas de campo esos controles valen 0: la nota de los controles de la carta no podrá superar {_pct(rate)}." if missing else "")
                   + (f" Sin documentación en dominios críticos: {_join(sorted({c['domain'] for c in critical_missing if c['domain']})[:3]) or str(len(critical_missing)) + ' control(es)'}."
                      if critical_missing else ""))
        rows.append({"id": a["id"], "code": a["code"], "title": a.get("title") or "", "unit": a["unit_name"], "phase": a.get("phase"),
                     "period": {"from": str(a.get("period_from") or ""), "to": str(a.get("period_to") or "")},
                     "counts": counts, "requested": requested, "received": received, "rate": rate, "summary": summary,
                     "ceiling": rate, "critical_missing": critical_missing,
                     "letter": [{"ref": c["ref"], "question": _cut(c["question"], 200), "status": c["status"],
                                 "note": _cut(c.get("note"), 200), "documents": c.get("documents", 0)} for c in a.get("letter") or []]})
    requested = sum(totals.values())
    received = totals["ACTUALIZADA"] + totals["DESACTUALIZADA"]
    rate = round(received / requested * 100, 2) if requested else None
    low = [r["code"] for r in rows if r["rate"] is not None and r["rate"] < 50]
    introduction = (
        f"La Contraloría Corporativa de {company}, a través de su equipo de Auditoría de Sistemas, presenta el Informe de "
        f"Documentación {code} sobre {len(rows)} auditoría(s) de sistemas en fase de Documentación. Por cada control que la "
        f"unidad declaró documentado en el levantamiento se pidió su documentación mediante la carta de solicitud; el informe "
        f"muestra lo obtenido, lo desactualizado, lo no entregado y lo que quedó sin respuesta.")
    scope = (f"Comprende {len(rows)} auditoría(s) en fase de Documentación. Criterio de selección: {filters_text}. "
             "Se considera lo registrado en SICAS a la fecha de emisión; la fase sigue abierta y puede variar.")
    objectives = ([objective] if objective else []) + [
        "Informar el estado de la documentación solicitada a cada unidad mediante la carta de solicitud.",
        "Identificar los controles sin documentación o sin respuesta, que bajan la calificación en Pruebas de campo.",
        "Apoyar el seguimiento con las unidades para obtener la documentación pendiente.",
    ]
    conclusion = [f"Se pidió la documentación de {requested} control(es) y se obtuvo la de {received} "
                  f"({_pct(rate) if rate is not None else 'sin datos'}): {totals['ACTUALIZADA']} actualizada, {totals['DESACTUALIZADA']} "
                  f"desactualizada, {totals['NO_ENTREGADA']} no entregada y {totals['SIN_RESPUESTA']} sin respuesta."]
    if low:
        conclusion.append(f"Menos de la mitad de la documentación se obtuvo en {_join(low)}: se recomienda gestionar la respuesta de esas unidades antes de Pruebas de campo.")
    crit = [(r["code"], r["unit"], len(r["critical_missing"])) for r in rows if r["critical_missing"]]
    if crit:
        conclusion.append(f"Faltan documentos de controles críticos (accesos, respaldos y demás dominios críticos) en {_join(f'{u} ({n})' for _, u, n in crit[:4])}: "
                          "son los primeros que deben gestionarse, porque su ausencia es por sí misma una brecha de riesgo alto.")
    ceilings = [r for r in rows if r["rate"] is not None and r["rate"] < 100]
    if ceilings:
        worst = min(ceilings, key=lambda r: r["rate"])
        conclusion.append(f"Con lo obtenido hasta hoy, la nota de los controles de la carta en Pruebas de campo no podrá superar el porcentaje "
                          f"de documentación obtenida; el techo más bajo es {worst['unit']} ({_pct(worst['rate'])}).")
    if totals["DESACTUALIZADA"]:
        conclusion.append("La documentación desactualizada debe actualizarse y aprobarse por la unidad responsable.")
    if totals["PENDIENTE"]:
        conclusion.append(f"Quedan {totals['PENDIENTE']} control(es) sin registrar lo obtenido.")
    return {"kind": "DOCUMENTACION", "code": code, "title": title, "company": company, "domain": "SISTEMAS", "revision": revision,
            "generated_on": today.isoformat(), "author": author, "filters": filters_text,
            "introduction": introduction, "scope": scope, "objectives": objectives,
            "kpis": {"audits": len(rows), "units": len({r["unit"] for r in rows}), "requested": requested, "received": received,
                     "rate": rate, "totals": totals},
            "audits": rows, "conclusion": conclusion, "conclusion_auto": list(conclusion), "conclusion_custom": False}
