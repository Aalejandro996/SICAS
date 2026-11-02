"""Motor de conclusiones: análisis y redacción de la conclusión de cada informe (lógica pura, sin base de datos).

Informe final de una auditoría (`audit_conclusion`), en párrafos:
  1. Opinión de Contraloría, coherente con la escala de calificación de la auditoría y con sus hallazgos:
       desfavorable                calificación no satisfactoria, o 3 o más hallazgos de riesgo alto
       con salvedades              calificación aceptable o necesita mejoras, o algún hallazgo de riesgo alto
       favorable con observaciones calificación excelente o satisfactoria con hallazgos de riesgo medio o bajo
       favorable                   calificación excelente o satisfactoria sin hallazgos de riesgo medio o alto
  2. Análisis propio del tipo de auditoría:
       operativa / especial  -> cédulas más débiles y cuestionarios (índice, riesgo y bloques que no cumplen),
                                con la prevención de LC/FT/FPADM aparte;
       administrativa / financiera -> cédulas de proceso más débiles;
       Sistemas -> nota por fase, documentación obtenida de la carta y dominios críticos con brechas.
  3. Causas comunes: temas normativos que concentran los hallazgos, con la causa del catálogo.
  4. Comparación con la auditoría anterior de la misma unidad: variación de la nota y temas que se repiten.
  5. Limitaciones al alcance y Plan de Acción Correctiva (PAC).
La Evaluación TI de la sucursal no participa (es informativa).
"""
from __future__ import annotations

from .scoring import RATING_LABEL

RISKS = ("ALTO", "MEDIO", "BAJO")
SITUATIONS = ("CRITICA", "ATENCION", "ACEPTABLE", "FAVORABLE", "SIN_CALIFICAR")
OPINION = {"DESFAVORABLE": "desfavorable", "SALVEDADES": "con salvedades", "OBSERVACIONES": "favorable con observaciones",
           "FAVORABLE": "favorable", "SIN_CALIFICAR": "no determinable (sin ítems calificados)"}
GOOD_RATINGS = ("EXCELENTE", "SATISFACTORIO")
MID_RATINGS = ("ACEPTABLE", "NECESITA_MEJORAS")
KIND_LABEL = {"OPERATIVA": "operativa", "ESPECIAL": "especial", "ADMINISTRATIVA": "administrativa",
              "FINANCIERA": "financiera", "SISTEMAS": "de sistemas y tecnología de la información"}
PHASE_LABEL = {"LEVANTAMIENTO": "Levantamiento de información", "DOCUMENTACION": "Documentación",
               "PRUEBAS_CAMPO": "Pruebas de campo"}
LCFT_KIND = "LCFT"
WEAK_SHEET = 85.0          # una cédula por debajo de este porcentaje se menciona como débil
MAX_LISTED = 3


def situation(score: float | None, by_risk: dict) -> str:
    high, medium = by_risk.get("ALTO", 0), by_risk.get("MEDIO", 0)
    if high >= 3 or (score is not None and score < 50):
        return "CRITICA"
    if high >= 1 or (score is not None and score < 70):
        return "ATENCION"
    if medium >= 1 or (score is not None and score < 85):
        return "ACEPTABLE"
    return "FAVORABLE" if score is not None or by_risk.get("BAJO", 0) else "SIN_CALIFICAR"


def opinion(rating: str | None, by_risk: dict) -> str:
    """Opinión de Contraloría a partir de la calificación (escala de la auditoría) y del riesgo de los hallazgos."""
    high, medium, low = by_risk.get("ALTO", 0), by_risk.get("MEDIO", 0), by_risk.get("BAJO", 0)
    if rating == "NO_SATISFACTORIA" or high >= 3:
        return "DESFAVORABLE"
    if rating in MID_RATINGS or high:
        return "SALVEDADES"
    if rating in GOOD_RATINGS:
        return "OBSERVACIONES" if medium or low else "FAVORABLE"
    return "OBSERVACIONES" if medium or low else "SIN_CALIFICAR"


def count_risks(observations: list[dict]) -> dict:
    return {r: sum(1 for o in observations if o.get("risk") == r) for r in RISKS}


def pct(v) -> str:
    return "sin calificar" if v is None else f"{float(v):.1f} %"


def join(words) -> str:
    words = [w for w in words if w]
    if not words:
        return ""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " y " + words[-1]


def dmy(v) -> str:
    v = str(v or "")[:10]
    return f"{v[8:10]}/{v[5:7]}/{v[:4]}" if len(v) == 10 else "—"


def kind_label(audit_kind: str | None, domain: str | None = None) -> str:
    if str(domain or "").upper() == "SISTEMAS":
        return KIND_LABEL["SISTEMAS"]
    return KIND_LABEL.get(str(audit_kind or "").upper(), "")


def topic_counts(observations: list[dict]) -> list[dict]:
    """Temas de los hallazgos (cada observación trae `topic`, `topic_label` y `topic_cause`), del más frecuente al menos."""
    out: dict[str, dict] = {}
    for o in observations:
        key = o.get("topic")
        if not key:
            continue
        t = out.setdefault(key, {"topic": key, "label": o.get("topic_label") or key, "cause": o.get("topic_cause") or "",
                                 "total": 0, "high": 0})
        t["total"] += 1
        t["high"] += 1 if o.get("risk") == "ALTO" else 0
    return sorted(out.values(), key=lambda t: (-t["high"], -t["total"], t["label"]))


def trend_sentence(score: float | None, previous: dict | None, subject: str = "la calificación") -> str:
    """Variación de la nota frente a la auditoría anterior de la unidad."""
    if not previous or previous.get("score") is None or score is None:
        return ""
    delta = round(float(score) - float(previous["score"]), 1)
    if abs(delta) < 1:
        return f"{subject[0].upper() + subject[1:]} se mantuvo en un nivel similar ({pct(previous['score'])} a {pct(score)})"
    word = "mejoró" if delta > 0 else "desmejoró"
    return f"{subject[0].upper() + subject[1:]} {word} {abs(delta):.1f} puntos ({pct(previous['score'])} a {pct(score)})"


def repeated_topics(current: list[dict], previous: dict | None) -> list[str]:
    if not previous:
        return []
    before = set(previous.get("topics") or [])
    return [t["label"] for t in topic_counts(current) if t["topic"] in before]


def comparison(score: float | None, observations: list[dict], previous: dict | None, unit: str) -> str:
    if previous is None:
        return f"Es la primera auditoría de {unit} registrada en SICAS; servirá de línea base para las siguientes."
    head = f"Frente a la auditoría anterior a {unit} ({previous['code']}, cerrada el {dmy(previous.get('closed_at'))})"
    trend = trend_sentence(score, previous)
    text = head + (f": {trend[0].lower() + trend[1:]}." if trend else ".")
    rep = repeated_topics(observations, previous)
    if rep:
        text += (f" Se repiten hallazgos en {join(rep[:MAX_LISTED])}, lo que indica que las acciones correctivas anteriores "
                 "no fueron suficientes o no se sostuvieron en el tiempo.")
    elif previous.get("topics"):
        text += " No se repiten los temas de los hallazgos anteriores."
    return text


def _weak_sheets(sheets: list[dict]) -> list[dict]:
    rated = [s for s in sheets if s.get("final") is not None and s.get("kind") != LCFT_KIND]
    return sorted((s for s in rated if float(s["final"]) < WEAK_SHEET), key=lambda s: float(s["final"]))[:MAX_LISTED]


def _questionnaire_sentence(q: dict) -> str:
    risk = {"BAJO": "bajo", "MEDIO": "medio", "ALTO": "alto"}.get(q.get("risk") or "", "")
    text = f"En «{q['title']}» el {q.get('index_label') or 'índice de cumplimiento'} es {pct(q.get('index'))}" + (f" (riesgo {risk})" if risk else "")
    crit = q.get("critical") or []
    return text + (f" y no cumplen el promedio requerido los bloques {join(crit[:MAX_LISTED])}." if crit else ".")


def _branch_analysis(sheets, questionnaires) -> list[str]:
    out = []
    weak = _weak_sheets(sheets)
    if weak:
        out.append("Las cédulas con menor calificación son " + join(f"«{s['title']}» ({pct(s['final'])})" for s in weak) + ".")
    elif any(s.get("final") is not None and s.get("kind") != LCFT_KIND for s in sheets):
        out.append("Las cédulas de la operación calificadas superan el 85 %.")
    for q in questionnaires:
        if q.get("kind") != LCFT_KIND and q.get("index") is not None:
            out.append(_questionnaire_sentence(q))
    lcft = next((q for q in questionnaires if q.get("kind") == LCFT_KIND and q.get("index") is not None), None)
    if lcft:
        out.append(_questionnaire_sentence({**lcft, "title": "Prevención LC/FT/FPADM"}).rstrip(".")
                   + "; el cumplimiento de la normativa de prevención (Providencia SUDEASEG SAA-01-0536-2024) es de atención "
                   + ("prioritaria." if lcft.get("risk") in ("ALTO", "MEDIO") or lcft.get("critical") else "ordinaria."))
    return out


def _process_analysis(sheets) -> list[str]:
    weak = _weak_sheets(sheets)
    if weak:
        return ["Los procesos con menor calificación son " + join(f"«{s['title']}» ({pct(s['final'])})" for s in weak)
                + ": sus controles no aseguran de forma consistente la integridad de las operaciones revisadas."]
    if any(s.get("final") is not None for s in sheets):
        return ["Los procesos revisados presentan controles que operan de forma consistente (todas las cédulas superan el 85 %)."]
    return []


def _systems_analysis(systems: dict | None) -> list[str]:
    if not systems:
        return []
    out = []
    phases = [p for p in systems.get("phases") or [] if p.get("score") is not None]
    if phases:
        out.append("Por fase: " + join(f"{PHASE_LABEL.get(p['phase'], p['phase'])} {pct(p['score'])}" for p in phases) + ".")
    req, rec = systems.get("requested") or 0, systems.get("received") or 0
    if req:
        out.append(f"De los {req} controles pedidos en la carta de solicitud se obtuvo la documentación de {rec} "
                   f"({pct(rec / req * 100)}); los no documentados valen 0 en Pruebas de campo.")
    crit = systems.get("critical_domains") or []
    if crit:
        out.append(f"Presentan brechas dominios críticos para la continuidad y la seguridad de la información: {join(crit[:4])}; "
                   "su atención debe priorizarse.")
    return out


def audit_conclusion(*, preliminary: bool, audit_kind: str | None, domain: str | None, modality: str, unit: str,
                     overall: dict, sheets: list[dict], questionnaires: list[dict], observations: list[dict],
                     limitations: int, previous: dict | None, systems: dict | None = None) -> str:
    """Conclusión del informe previo o final de una auditoría, en párrafos separados por una línea en blanco."""
    score = overall.get("final")
    by_risk = count_risks(observations)
    n = sum(by_risk.values())
    sit = opinion(overall.get("rating"), by_risk)
    if sit == "FAVORABLE" and any(q.get("critical") or q.get("risk") in ("ALTO", "MEDIO") for q in questionnaires):
        sit = "OBSERVACIONES"          # un cuestionario con bloques que no cumplen impide una opinión sin observaciones
    kind = kind_label(audit_kind, domain)
    head = "Con carácter PRELIMINAR, como resultado de la auditoría" if preliminary else "Como resultado de la auditoría"
    p1 = (f"{head} {kind + ' ' if kind else ''}{modality.lower()} practicada a {unit}, la opinión de Contraloría sobre el "
          f"control interno evaluado es {OPINION[sit].upper()}: ")
    rating = RATING_LABEL.get(overall.get("rating"), "").lower()
    p1 += (f"calificación de {pct(score)}" + (f" ({rating})" if rating else "") if score is not None else "sin calificación") + (
        f" y {n} observación(es) ({by_risk['ALTO']} de riesgo alto, {by_risk['MEDIO']} medio y {by_risk['BAJO']} bajo)."
        if n else " y sin observaciones.")
    paragraphs = [p1]

    if str(domain or "").upper() == "SISTEMAS":
        analysis = _systems_analysis(systems)
    elif str(audit_kind or "").upper() in ("ADMINISTRATIVA", "FINANCIERA"):
        analysis = _process_analysis(sheets)
    else:
        analysis = _branch_analysis(sheets, questionnaires)
    if analysis:
        paragraphs.append(" ".join(analysis))

    topics = topic_counts(observations)
    if topics:
        main = topics[0]
        text = f"Los hallazgos se concentran en {join(t['label'] + ' (' + str(t['total']) + ')' for t in topics[:MAX_LISTED])}."
        if main.get("cause"):
            text += f" Causa común identificada en {main['label']}: {main['cause'][0].lower() + main['cause'][1:]}"
            text += "" if text.endswith(".") else "."
        paragraphs.append(text)

    paragraphs.append(comparison(score, observations, previous, unit))

    closing = []
    if limitations:
        closing.append(f"Se registraron {limitations} excepción(es) por información no recibida, que constituyen limitaciones al "
                       "alcance y se detallan en este informe.")
    if overall.get("final_method") == "PROMEDIO_FASES":
        closing.append("La nota final corresponde al promedio de las fases de levantamiento de información, documentación y "
                       "pruebas de campo.")
    if overall.get("manual_override"):
        closing.append("La calificación global fue ajustada manualmente por el auditor, con la justificación indicada en este informe.")
    if n:
        closing.append("Las observaciones deben atenderse mediante el Plan de Acción Correctiva (PAC), "
                       + ("comenzando por las de riesgo alto, " if by_risk["ALTO"] else "")
                       + "con responsables y fechas de cumplimiento que Contraloría verificará en el seguimiento.")
    if closing:
        paragraphs.append(" ".join(closing))
    return "\n\n".join(paragraphs)


def annotate_topics(observations: list[dict], catalog: list[dict]) -> list[dict]:
    """Agrega a cada observación su tema del catálogo (`topic`, `topic_label`, `topic_cause`).

    Las observaciones generadas por el motor traen el tema en su clave (`<cédula>:<tema>`); las demás se clasifican
    por palabras clave de su título, criterio y condición. Sin catálogo se devuelven tal cual.
    """
    if not catalog:
        return observations
    from .regulatory_rules import topic_for

    by_key = {c["topic"]: c for c in catalog}
    out = []
    for o in observations:
        key = str(o.get("rule_key") or "").rsplit(":", 1)[-1]
        t = by_key.get(key) or topic_for(catalog, o.get("title"), o.get("criteria"), o.get("condition"))
        out.append({**o, "topic": t["topic"], "topic_label": t.get("label") or t["topic"], "topic_cause": t.get("cause") or ""})
    return out


def is_lcft_topic(topic: str | None) -> bool:
    return str(topic or "") == "lcft" or str(topic or "").startswith("lcft_")
