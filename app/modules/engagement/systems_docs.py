"""Auditoría de Sistemas: fases de Documentación y Pruebas de campo (lógica pura).

Documentación (fase 2): solo se trabajan los controles pedidos en la carta de solicitud, es decir, los
que la unidad declaró documentados en el Levantamiento. Por cada uno el auditor registra lo obtenido:
  ACTUALIZADA     documento recibido y vigente           -> soporte SI, evidencia ACTUALIZADO
  DESACTUALIZADA  documento recibido pero desactualizado -> soporte SI, evidencia DESACTUALIZADO
  NO_ENTREGADA    la unidad no tiene o no entregó        -> soporte NO, evidencia INEXISTENTE
  SIN_RESPUESTA   la unidad no respondió la carta        -> soporte NO, evidencia INEXISTENTE
La existencia del control se mantiene como en el Levantamiento. El documento se adjunta como evidencia.

Pruebas de campo (fase 3), sobre los mismos controles de la carta:
  - con documentación: tres preguntas Sí/No que alimentan la fórmula 40/30/30:
      q2 ¿se ejecuta como lo describe el documento?  -> existencia (40 %)
      q1 ¿el documento está aprobado y vigente?        -> soporte documental (30 %)
      q3 ¿hay evidencia de su ejecución en el período? -> evidencia (30 %)
    Resultado: 3 Sí = cumple, 1 o 2 = cumple parcialmente, 0 = no cumple.
  - sin documentación: justificativo obligatorio para cerrar la fase; el control vale 0.
"""
from __future__ import annotations

DOC_STATUS = {
    "ACTUALIZADA": ("SI", "ACTUALIZADO"),
    "DESACTUALIZADA": ("SI", "DESACTUALIZADO"),
    "NO_ENTREGADA": ("NO", "INEXISTENTE"),
    "SIN_RESPUESTA": ("NO", "INEXISTENTE"),
}
DOC_LABEL = {"ACTUALIZADA": "Recibida y actualizada", "DESACTUALIZADA": "Recibida pero desactualizada",
             "NO_ENTREGADA": "No la tiene / no la entregó", "SIN_RESPUESTA": "Sin respuesta de la unidad"}
WITH_DOCS = ("ACTUALIZADA", "DESACTUALIZADA")
QUESTIONS = (("q1", "¿El documento está aprobado y vigente?"),
             ("q2", "¿El control se ejecuta como lo describe el documento?"),
             ("q3", "¿Hay evidencia de su ejecución en el período revisado?"))
RESULT_LABEL = {"CUMPLE": "Cumple", "PARCIAL": "Cumple parcialmente", "NO_CUMPLE": "No cumple", "SIN_DOC": "Sin documentación (0)"}
MIN_JUSTIFICATION = 15


def _closed(item: dict, phase: str) -> dict | None:
    """Resultados del control al cierre de la fase, o None si la fase no se cerró."""
    pr = (item.get("phase_results") or {}).get(phase)
    if pr is None:
        return None
    v = (pr.get("results") or {}).get(item.get("ref"))
    return v if isinstance(v, dict) else {}


def _current(item: dict) -> dict:
    v = (item.get("results") or {}).get(item.get("ref"))
    return v if isinstance(v, dict) else {}


def in_letter(item: dict) -> bool:
    """El control se pidió en la carta: la unidad lo declaró documentado en el Levantamiento."""
    closed = _closed(item, "LEVANTAMIENTO")
    src = closed if closed is not None else _current(item)
    return str(src.get("documental") or "").upper() == "SI"


def levantamiento_control(item: dict) -> str:
    closed = _closed(item, "LEVANTAMIENTO")
    src = closed if closed is not None else _current(item)
    return str(src.get("control") or "").upper()


def doc_status_of(result: dict) -> str | None:
    """Estado de la documentación de un resultado; los registros anteriores al cambio se deducen de sus campos."""
    st = str(result.get("doc_status") or "").upper()
    if st in DOC_STATUS:
        return st
    doc, ev = str(result.get("documental") or "").upper(), str(result.get("evidencia") or "").upper()
    if doc == "SI":
        return "DESACTUALIZADA" if ev == "DESACTUALIZADO" else "ACTUALIZADA" if ev == "ACTUALIZADO" else None
    if doc == "NO":
        return "NO_ENTREGADA"
    return None


def documentation_status(item: dict) -> str | None:
    """Lo obtenido en la fase de Documentación: el cierre de la fase o, si sigue abierta, lo que registró el auditor.

    Mientras la fase está abierta, lo declarado en el Levantamiento no cuenta como obtenido: queda pendiente.
    """
    st = str(_current(item).get("doc_status") or "").upper()
    if st in DOC_STATUS:
        return st          # lo registrado (Pruebas de campo conserva el estado obtenido en Documentación)
    closed = _closed(item, "DOCUMENTACION")
    return doc_status_of(closed) if closed is not None else None


def documentation_result(item: dict, payload: dict) -> dict:
    """Resultado del control en Documentación a partir de lo que registra el auditor."""
    st = str(payload.get("doc_status") or "").upper()
    if st and st not in DOC_STATUS:
        raise ValueError("Estado de la documentación inválido")
    note = str(payload.get("doc_note") or "").strip()[:1000]
    out = {"control": levantamiento_control(item), "doc_status": st, "doc_note": note}
    if st:
        out["documental"], out["evidencia"] = DOC_STATUS[st]
    return out


def field_outcome(answers: dict) -> str | None:
    yes = sum(1 for k, _ in QUESTIONS if answers.get(k) == "SI")
    if any(answers.get(k) not in ("SI", "NO") for k, _ in QUESTIONS):
        return None
    return "CUMPLE" if yes == 3 else "NO_CUMPLE" if yes == 0 else "PARCIAL"


def field_result(item: dict, payload: dict) -> dict:
    """Resultado del control en Pruebas de campo según tenga o no documentación (conserva la nota de Documentación)."""
    status = documentation_status(item)
    doc_note = _current(item).get("doc_note") or (_closed(item, "DOCUMENTACION") or {}).get("doc_note") or ""
    if status in WITH_DOCS:
        answers = {k: str(payload.get(k) or "").upper() for k, _ in QUESTIONS}
        if any(v not in ("", "SI", "NO") for v in answers.values()):
            raise ValueError("Las preguntas de la prueba se responden Sí o No")
        out = {**answers, "doc_status": status, "doc_note": doc_note, "test_note": str(payload.get("test_note") or "").strip()[:1000]}
        outcome = field_outcome(answers)
        if outcome:
            out.update(control=answers["q2"], documental=answers["q1"],
                       evidencia="ACTUALIZADO" if answers["q3"] == "SI" else "INEXISTENTE", outcome=outcome)
        return out
    justification = str(payload.get("justification") or "").strip()[:2000]
    out = {"doc_status": status or "NO_ENTREGADA", "doc_note": doc_note, "justification": justification,
           "control": levantamiento_control(item), "documental": "NO", "evidencia": "INEXISTENTE"}
    if justification:
        out.update(sin_doc=True, outcome="SIN_DOC")
    return out


def field_done(item: dict) -> bool:
    r = _current(item)
    if r.get("outcome") == "SIN_DOC":
        return len(str(r.get("justification") or "").strip()) >= MIN_JUSTIFICATION
    if r.get("outcome") in ("CUMPLE", "PARCIAL", "NO_CUMPLE"):
        return True
    # Auditorías que cerraron Documentación antes del cambio: se acepta la prueba registrada con la fórmula anterior.
    legacy = "doc_status" not in (_closed(item, "DOCUMENTACION") or {})
    return legacy and str(r.get("control") or "").upper() in ("SI", "NO")


def pending(items: list[dict], phase: str) -> list[str]:
    """Controles de la carta que faltan para cerrar la fase (Documentación o Pruebas de campo)."""
    out = []
    for it in items:
        if not in_letter(it):
            continue
        if phase == "DOCUMENTACION" and documentation_status(it) is None:
            out.append(it["ref"])
        elif phase == "PRUEBAS_CAMPO" and not field_done(it):
            out.append(it["ref"])
    return out


def letter_rows(items: list[dict], criteria: list[dict], evidence_by_item: dict | None = None) -> list[dict]:
    """Controles de la carta con lo obtenido en Documentación (para pantallas e informes)."""
    by_code = {c["code"]: c for c in criteria}
    rows = []
    for it in items:
        if not in_letter(it):
            continue
        st = documentation_status(it)
        c = by_code.get(it["ref"], {})
        rows.append({"ref": it["ref"], "section": c.get("section") or "", "question": c.get("text") or it["ref"],
                     "status": st, "status_label": DOC_LABEL.get(st, "Pendiente"),
                     "note": (_current(it).get("doc_note") or ""), "documents": len((evidence_by_item or {}).get(it.get("id"), []))})
    return rows
