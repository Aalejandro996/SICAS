"""Documentos de las fases 2 y 3 de la Auditoría de Sistemas (lógica pura + PDF).

- Carta de solicitud de documentación: pide a la unidad la documentación de los controles que
  declaró documentados en el levantamiento, esté actualizada o no.
- Programa de pruebas de campo: lista los controles documentados (SI) en la fase de
  Documentación, con el procedimiento de prueba sugerido para cada uno.
"""
from __future__ import annotations

import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import observation_rules

NAVY = colors.HexColor("#1F3864")
EVIDENCE = {"ACTUALIZADO": "Actualizada", "DESACTUALIZADO": "Desactualizada", "INEXISTENTE": "Inexistente"}


def _answer(item: dict, phase: str | None, field: str) -> str:
    """Respuesta al cierre de la fase indicada; si la fase no se cerró, la respuesta vigente."""
    code = item.get("ref")
    closed = (((item.get("phase_results") or {}).get(phase) or {}).get("results") or {}) if phase else {}
    value = closed.get(code) if code in closed else (item.get("results") or {}).get(code)
    return str(value.get(field) or "").upper() if isinstance(value, dict) else ""


def documented_controls(worksheets: list[dict], phase: str) -> list[dict]:
    """Controles con soporte documental SI al cierre de `phase`, en el orden de la cédula."""
    out = []
    for ws in worksheets:
        if ws.get("kind") != "SISTEMAS":
            continue
        criteria = {c["code"]: c for c in ws.get("criteria") or []}
        for it in ws.get("items") or []:
            if _answer(it, phase, "documental") != "SI":
                continue
            crit = criteria.get(it["ref"], {})
            out.append({
                "ref": it["ref"], "section": crit.get("section") or "", "question": crit.get("text") or it["ref"],
                "evidence": EVIDENCE.get(_answer(it, phase, "evidencia"), "No indicada"),
                "control": _answer(it, phase, "control"),
                "test": observation_rules.field_test_for(crit),
            })
    return out


def _styles():
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10, leading=14)
    return {
        "body": body,
        "cell": ParagraphStyle("c", parent=body, fontSize=8.5, leading=11),
        "hdr": ParagraphStyle("h", parent=body, fontSize=8.5, leading=11, textColor=colors.white, fontName="Helvetica-Bold"),
        "h1": ParagraphStyle("h1", parent=ss["Heading1"], fontSize=14, textColor=NAVY, spaceAfter=8),
        "small": ParagraphStyle("s", parent=body, fontSize=8, leading=10, textColor=colors.HexColor("#555555")),
    }


def _p(text, style):
    return Paragraph(escape("" if text is None else str(text)).replace("\n", "<br/>"), style)


def _table(rows, widths):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TOPPADDING", (0, 0), (-1, -1), 3),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _doc(title: str, company: str):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                            title=title, author=company)
    return buf, doc


def _signature(team: list[dict], st):
    names = "; ".join(f"{t['name']} — {t.get('system_role') or 'Auditor'}" for t in team) or "Equipo auditor"
    return [Spacer(1, 26), _p("Atentamente,", st["body"]), Spacer(1, 30), _p(names, st["body"]),
            _p("Contraloría Corporativa — Auditoría de Sistemas", st["small"])]


def documentation_request_pdf(*, audit: dict, team: list[dict], controls: list[dict], company: str, due: date | None,
                              today: date) -> bytes:
    st = _styles()
    buf, doc = _doc(f"Solicitud de documentación {audit['code']}", company)
    to = audit.get("contact_name") or "Responsable de la unidad"
    role = audit.get("contact_role") or ""
    deadline = due.strftime("%d/%m/%Y") if due else "la fecha acordada con el equipo auditor"
    s = [
        _p(company, st["small"]), _p("Contraloría Corporativa", st["small"]), Spacer(1, 10),
        _p(f"Fecha: {today.strftime('%d/%m/%Y')}", st["body"]),
        _p(f"Ref.: Auditoría {audit['code']} — Expediente {audit.get('file_code') or ''}", st["body"]), Spacer(1, 10),
        _p(f"Señor(a): {to}" + (f"\n{role}" if role else ""), st["body"]),
        _p(audit.get("unit_name") or "", st["body"]), Spacer(1, 12),
        Paragraph("Solicitud de documentación — Fase 2 de la Auditoría de Sistemas", st["h1"]),
        _p("Como parte de la auditoría de sistemas en curso, y de acuerdo con lo informado por su unidad durante el "
           "levantamiento de información, solicitamos su colaboración para suministrar la documentación de soporte de los "
           f"controles que se indican a continuación, a más tardar el {deadline}.", st["body"]), Spacer(1, 6),
        _p("Se requiere la documentación existente de cada control, se encuentre actualizada o no (políticas, procedimientos, "
           "manuales, actas, registros, reportes o evidencias de ejecución), indicando en cada caso su fecha de aprobación "
           "o de última actualización.", st["body"]), Spacer(1, 10),
    ]
    if controls:
        rows = [[Paragraph(x, st["hdr"]) for x in ("N°", "Control", "Sección", "Pregunta de auditoría", "Evidencia declarada")]]
        rows += [[_p(i, st["cell"]), _p(c["ref"], st["cell"]), _p(c["section"], st["cell"]), _p(c["question"], st["cell"]),
                  _p(c["evidence"], st["cell"])] for i, c in enumerate(controls, 1)]
        s.append(_table(rows, [0.9 * cm, 1.6 * cm, 3.6 * cm, 8.4 * cm, 3 * cm]))
    else:
        s.append(_p("En el levantamiento de información no se declararon controles con soporte documental.", st["body"]))
    s += [Spacer(1, 10), _p("La información será tratada con carácter confidencial y utilizada exclusivamente para los fines "
                            "de la auditoría.", st["body"])]
    s += _signature(team, st)
    doc.build(s)
    return buf.getvalue()


def field_tests_pdf(*, audit: dict, team: list[dict], controls: list[dict], company: str, today: date) -> bytes:
    st = _styles()
    buf, doc = _doc(f"Programa de pruebas de campo {audit['code']}", company)
    s = [
        _p(company, st["small"]), _p("Contraloría Corporativa — Auditoría de Sistemas", st["small"]), Spacer(1, 8),
        Paragraph(f"Programa de pruebas de campo — {audit['code']}", st["h1"]),
        _p(f"Unidad: {audit.get('unit_name') or ''} · Fecha: {today.strftime('%d/%m/%Y')} · Controles a probar: {len(controls)}",
           st["body"]), Spacer(1, 6),
        _p("Se prueban en campo los controles que resultaron documentados (SI) en la fase de Documentación. Para cada uno, "
           "registre en SICAS el resultado de la prueba (existencia, soporte documental y evidencia) y adjunte la evidencia "
           "obtenida. Los controles no documentados conservan el resultado de la fase de Documentación.", st["body"]),
        Spacer(1, 10),
    ]
    if controls:
        rows = [[Paragraph(x, st["hdr"]) for x in ("N°", "Control", "Pregunta de auditoría", "Procedimiento de prueba", "Resultado")]]
        rows += [[_p(i, st["cell"]), _p(c["ref"], st["cell"]), _p(c["question"], st["cell"]), _p(c["test"], st["cell"]), _p("", st["cell"])]
                 for i, c in enumerate(controls, 1)]
        s.append(_table(rows, [0.9 * cm, 1.6 * cm, 5.6 * cm, 6.9 * cm, 2.5 * cm]))
    else:
        s.append(_p("No hay controles documentados para probar en campo.", st["body"]))
    s += _signature(team, st)
    doc.build(s)
    return buf.getvalue()
