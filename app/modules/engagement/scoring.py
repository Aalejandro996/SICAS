"""
Calificación de cédulas (lógica pura).
  - Cada criterio se responde: CUMPLE (100), PARCIAL (50), NO_CUMPLE (0), NO_APLICA o EXCEPCION (no puntúan).
  - Nota automática de un ítem = promedio ponderado de los criterios que puntúan.
  - 2. El Auditor puede AJUSTARLA manualmente (0-100) con justificación obligatoria; la nota final es la manual.
  - Nota de cédula = promedio de las notas finales de sus ítems (o la manual de la cédula). Nota de auditoría = promedio
    de las cédulas (o la manual de la auditoría). Se conserva siempre la nota automática y la diferencia.
  - 3. EXCEPCION = información no recibida: no penaliza ni premia, pero queda como LIMITACIÓN AL ALCANCE visible en el informe.
"""
from __future__ import annotations

from dataclasses import dataclass

from .financial_rules import evaluate_criterion, RULE_SCORED

POINTS = {"CUMPLE": 100.0, "PARCIAL": 50.0, "NO_CUMPLE": 0.0}
# Sistemas: el control solo se responde SI o NO (PARCIAL no forma parte de la fórmula 40/30/30).
SYSTEM_CONTROL_VALUES = ("SI", "NO")
SYSTEM_DOC_POINTS = {"SI": 100.0, "NO": 0.0}
# Identifica la regla de cálculo vigente en las instantáneas por fase.
RULE_VERSION = "sicas-scoring-2026.10-sistemas-si-no"
SYSTEM_EVIDENCE_POINTS = {"ACTUALIZADO": 100.0, "DESACTUALIZADO": 50.0, "INEXISTENTE": 0.0}

def is_system_criteria(criteria: list[dict]) -> bool:
    return bool(criteria) and all(
        c.get("evaluation_mode") in {
            "ERP_TI",
            "SEC_TI",
            "SYSTEM_EXCEL",
        }
        for c in criteria
    )
DEFAULT_THRESHOLDS = {
    "excelente": 90,
    "satisfactorio": 70,
    "aceptable": 60,
    "mejora": 50,
}
# Escala de las auditorías operativas, especiales, administrativas y financieras (3 niveles):
#   No satisfactoria <= 33,3 · Aceptable > 33,3 y <= 50 · Excelente > 50.
AUDIT_THRESHOLDS = {"scale": "TRES_NIVELES", "excelente": 50, "aceptable": 33.3}

RATING_LABEL = {
    "EXCELENTE": "Excelente",
    "SATISFACTORIO": "Satisfactorio",
    "ACEPTABLE": "Aceptable",
    "NECESITA_MEJORAS": "Necesita mejoras",
    "NO_SATISFACTORIA": "No satisfactoria",
    "SIN_CALIFICAR": "Sin calificar",
}


class ScoreError(ValueError):
    pass


def system_item_score(criteria: list[dict], results: dict) -> float | None:
    # Replica la fórmula del Excel: Existencia 40% + Documento 30% + Evidencia 30%.
    num = den = 0.0
    for c in criteria:
        r = results.get(c["code"]) or {}
        if not isinstance(r, dict):
            continue
        control = str(r.get("control", "")).upper()
        doc = str(r.get("documental", "")).upper()
        evidence = str(r.get("evidencia", "")).upper()
        if control not in ("SI", "NO"):
            continue
        score = 0.0 if control == "NO" else 40.0
        if control == "SI":
            score += 0.3 * SYSTEM_DOC_POINTS.get(doc, 0.0)
            score += 0.3 * SYSTEM_EVIDENCE_POINTS.get(evidence, 0.0)
        w = float(c.get("weight") or 1)
        num += w * score
        den += w
    return None if den == 0 else round(num / den, 2)

def system_statistics(criteria: list[dict], items: list[dict]) -> dict:
    """Indicadores del cuestionario ERP/TI, calculados siempre en servidor."""
    by_code = {c["code"]: c for c in criteria}
    rows = []
    for it in items:
        code = it.get("ref")
        r = it.get("results") or {}
        if code not in by_code or not isinstance(r, dict):
            continue
        control = str(r.get(code, {}).get("control", "")).upper() if isinstance(r.get(code), dict) else ""
        doc = str(r.get(code, {}).get("documental", "")).upper() if isinstance(r.get(code), dict) else ""
        evidence = str(r.get(code, {}).get("evidencia", "")).upper() if isinstance(r.get(code), dict) else ""
        rows.append((control, doc, evidence, item_score(criteria, r)))
    total = len(criteria)
    answered = sum(1 for c, _, _, _ in rows if c in SYSTEM_CONTROL_VALUES)
    control_si = sum(1 for c, _, _, _ in rows if c == "SI")
    control_no = sum(1 for c, _, _, _ in rows if c == "NO")
    # Respuestas PARCIAL registradas antes del cambio de regla: no puntúan y quedan pendientes.
    control_partial = sum(1 for c, _, _, _ in rows if c == "PARCIAL")
    doc_si = sum(1 for _, d, _, _ in rows if d == "SI")
    evidence_updated = sum(1 for _, _, e, _ in rows if e == "ACTUALIZADO")
    evidence_outdated = sum(1 for _, _, e, _ in rows if e == "DESACTUALIZADO")
    evidence_missing = sum(1 for _, _, e, _ in rows if e == "INEXISTENTE")
    high = sum(1 for c, d, e, _ in rows if c == "NO" and d == "NO" and e == "INEXISTENTE")
    medium = sum(1 for c, d, e, _ in rows if c == "SI" and d == "SI" and e == "DESACTUALIZADO")
    scored = [score for _, _, _, score in rows if score is not None]
    compliance = round(sum(scored) / len(scored), 2) if scored else None
    exposure = round((sum(1 for c, d, _, _ in rows if c == "NO" and d == "NO") / total) * 100, 2) if total else None
    return {
        "total": total, "respondidas": answered, "pendientes": max(total - answered, 0),
        "controles_si": control_si, "controles_no": control_no, "controles_parcial": control_partial,
        "controles_documentados": doc_si, "evidencia_actualizada": evidence_updated,
        "evidencia_desactualizada": evidence_outdated, "evidencia_inexistente": evidence_missing,
        "brechas_alto": high, "brechas_medio": medium, "cumplimiento": compliance, "exposicion": exposure,
    }


def is_financial_criteria(criteria: list[dict]) -> bool:
    return bool(criteria) and all(
        str(c.get("evaluation_mode") or "").upper() == "FINANCIAL_CATALOG"
        for c in criteria
    )


def _criterion_result(results: dict, criterion: dict):
    code = criterion.get("code")
    source_id = criterion.get("source_id")

    if code in results:
        return results.get(code)

    if source_id in results:
        return results.get(source_id)

    return None


def financial_item_score(
    criteria: list[dict],
    results: dict,
) -> float | None:
    num = den = 0.0

    for c in criteria:
        response = _criterion_result(results, c)

        decision = evaluate_criterion(
            str(c.get("template_code") or ""),
            c,
            response,
            exception=bool(
                str(response or "").strip().upper() == "EXCEPCION"
            ),
        )

        if decision.status != RULE_SCORED:
            continue

        if decision.score is None:
            continue

        w = float(c.get("weight") or 1)
        num += w * float(decision.score)
        den += w

    return None if den == 0 else round(num / den, 2)


def item_score(criteria: list[dict], results: dict) -> float | None:
    # Auditoría de Sistemas: permanece exactamente en su rama propia.
    if is_system_criteria(criteria):
        return system_item_score(criteria, results)

    # Auditoría Financiera: usa exclusivamente el motor financiero.
    if is_financial_criteria(criteria):
        return financial_item_score(criteria, results)

    # Compatibilidad con la lógica genérica existente.
    num = den = 0.0
    for c in criteria:
        pts = POINTS.get(results.get(c["code"]))
        if pts is None:
            continue
        w = float(c.get("weight") or 1)
        num += w * pts
        den += w

    return None if den == 0 else round(num / den, 2)

def final_score(auto: float | None, manual) -> float | None:
    return float(manual) if manual is not None else auto


def validate_manual(score, reason: str, auto: float | None = None) -> tuple[float, str]:
    try:
        v = round(float(score), 2)
    except (TypeError, ValueError):
        raise ScoreError("La calificación manual debe ser un número entre 0 y 100")
    if not 0 <= v <= 100:
        raise ScoreError("La calificación manual debe estar entre 0 y 100")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ScoreError("Justifique el ajuste manual (mínimo 10 caracteres)")
    return v, reason


def mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return None if not vals else round(sum(vals) / len(vals), 2)


def rating(score: float | None, thresholds: dict | None = None) -> str:
    """
    Escala institucional:

      > 90       Excelente
      70 - 90    Satisfactorio
      60 - 69.99 Aceptable
      50 - 59.99 Necesita mejoras
      <= 49.99   No satisfactoria
    """
    t = {
        **DEFAULT_THRESHOLDS,
        **(thresholds or {}),
    }

    if score is None:
        return "SIN_CALIFICAR"

    value = float(score)

    if t.get("scale") == "TRES_NIVELES":
        if value > t["excelente"]:
            return "EXCELENTE"
        if value > t["aceptable"]:
            return "ACEPTABLE"
        return "NO_SATISFACTORIA"

    # Excelente: estrictamente mayor que 90.
    if value > t["excelente"]:
        return "EXCELENTE"

    # Satisfactorio: 70 hasta 90 inclusive.
    if value >= t["satisfactorio"]:
        return "SATISFACTORIO"

    # Aceptable: 60 hasta 69.99...
    if value >= t["aceptable"]:
        return "ACEPTABLE"

    # Necesita mejoras: 50 hasta 59.99...
    if value >= t["mejora"]:
        return "NECESITA_MEJORAS"

    # Menor de 50.
    return "NO_SATISFACTORIA"


@dataclass
class SheetSummary:
    items: int
    scored: int
    exceptions: int
    auto: float | None
    final: float | None
    manual_override: bool
    rating: str


def worksheet_summary(criteria: list[dict], items: list[dict], sheet_manual: float | None = None,
                      thresholds: dict | None = None) -> SheetSummary:
    finals, autos, exc = [], [], 0
    for it in items:
        a = item_score(criteria, it.get("results") or {})
        autos.append(a)
        finals.append(final_score(a, it.get("manual_score")))
        if it.get("info_exception") or "EXCEPCION" in (it.get("results") or {}).values():
            exc += 1
    auto = mean(finals)                       # promedio de las notas finales de los ítems
    sheet_manual = None if sheet_manual is None else float(sheet_manual)
    final = sheet_manual if sheet_manual is not None else auto
    return SheetSummary(len(items), sum(1 for f in finals if f is not None), exc, auto, final,
                        sheet_manual is not None, rating(final, thresholds))


def audit_summary(sheets: list[SheetSummary], manual: float | None = None, thresholds: dict | None = None) -> dict:
    auto = mean(s.final for s in sheets)
    manual = None if manual is None else float(manual)
    final = manual if manual is not None else auto
    return {"auto": auto, "final": final, "manual_override": manual is not None, "rating": rating(final, thresholds),
            "items": sum(s.items for s in sheets), "exceptions": sum(s.exceptions for s in sheets)}


# ------------------------------------------------------------------ indicadores de la evaluación (cuadro del informe)
SYSTEM_INDICATORS = (
    ("total", "Controles"),
    ("respondidas", "Respondidos"),
    ("controles_si", "Control: Sí"),
    ("controles_no", "Control: No"),
    ("controles_documentados", "Documentados"),
    ("evidencia_actualizada", "Evidencia actualizada"),
    ("brechas_alto", "Brechas altas"),
    ("brechas_medio", "Brechas medias"),
)


def _response_counts(criteria: list[dict], items: list[dict]) -> dict:
    """Cuenta respuestas de cédulas no sistemas: cumple, no cumple, no aplica y pendientes."""
    aff = answered = na = pending = 0
    for it in items:
        results = it.get("results") or {}
        for c in criteria:
            v = str(_criterion_result(results, c) or "").upper()
            if v == "CUMPLE":
                aff += 1
                answered += 1
            elif v in ("NO_CUMPLE", "PARCIAL"):
                answered += 1
            elif v in ("NO_APLICA", "EXCEPCION"):
                na += 1
            else:
                pending += 1
    return {"affirmative": aff, "answered": answered, "not_applicable": na, "pending": pending}


def evaluation_indicators(worksheets: list[dict], overall: dict, thresholds: dict | None = None) -> dict:
    """Cuadro de resultados por cédula: los indicadores que muestra la cédula y su calificación.

    Sistemas: los mismos indicadores del cuestionario ERP/TI (system_statistics).
    Otras cédulas: ítems, criterios respondidos, cumple, no cumple, no aplica y pendientes.
    """
    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    sheets = []
    for ws in worksheets:
        summary = worksheet_summary(ws["criteria"], ws["items"], ws.get("manual_score"), t)
        if is_system_criteria(ws["criteria"]):
            stats = system_statistics(ws["criteria"], ws["items"])
            indicators = [{"key": k, "label": label, "value": int(stats.get(k) or 0)} for k, label in SYSTEM_INDICATORS]
        else:
            counts = _response_counts(ws["criteria"], ws["items"])
            indicators = [
                {"key": "items", "label": "Ítems evaluados", "value": summary.items},
                {"key": "answered", "label": "Criterios respondidos", "value": counts["answered"]},
                {"key": "affirmative", "label": "Cumple", "value": counts["affirmative"]},
                {"key": "negative", "label": "No cumple / parcial", "value": counts["answered"] - counts["affirmative"]},
                {"key": "not_applicable", "label": "No aplica / excepción", "value": counts["not_applicable"]},
                {"key": "pending", "label": "Pendientes", "value": counts["pending"]},
            ]
        sheets.append({"id": ws.get("id"), "title": ws.get("title"), "kind": ws.get("kind"),
                       "score": summary.final, "rating": summary.rating, "items": summary.items, "indicators": indicators})
    return {"overall": {"score": overall.get("final"), "rating": overall.get("rating", "SIN_CALIFICAR"),
                        "items": sum(s["items"] for s in sheets)},
            "worksheets": sheets}


# ------------------------------------------------------------------ Auditoría de Sistemas: notas por fase
SYSTEM_PHASES = ("LEVANTAMIENTO", "DOCUMENTACION", "PRUEBAS_CAMPO", "INFORME")
SYSTEM_SCORED_PHASES = SYSTEM_PHASES[:3]


def systems_overall(base: dict, phase_scores: dict, current_phase: str | None, manual: float | None = None,
                    thresholds: dict | None = None) -> dict:
    """Calificación de una auditoría de Sistemas a partir de sus fases.

    Cada fase se califica con la fórmula vigente (40/30/30) al cerrarse. En la fase INFORME la
    nota final es el promedio simple de las fases cerradas 1, 2 y 3; antes de llegar a INFORME
    la nota vigente es la de la fase en curso. El ajuste manual global, si existe, prevalece.
    """
    phases = []
    for p in SYSTEM_SCORED_PHASES:
        closed = phase_scores.get(p)
        if closed is not None:
            score = None if closed.get("score") is None else float(closed["score"])
            phases.append({"phase": p, "score": score, "rating": rating(score, thresholds), "closed": True,
                           "closed_at": closed.get("closed_at")})
        elif current_phase == p:
            phases.append({"phase": p, "score": base.get("final"), "rating": base.get("rating"), "closed": False, "closed_at": None})
        else:
            phases.append({"phase": p, "score": None, "rating": "SIN_CALIFICAR", "closed": False, "closed_at": None})
    out = dict(base)
    if current_phase == "INFORME":
        auto = mean(ph["score"] for ph in phases if ph["closed"])
        auto = base.get("auto") if auto is None else auto
        final = float(manual) if manual is not None else auto
        out.update(auto=auto, final=final, rating=rating(final, thresholds), manual_override=manual is not None,
                   final_method="PROMEDIO_FASES")
    else:
        out["final_method"] = "FASE_EN_CURSO"
    out["phase_scores"] = phases
    return out
