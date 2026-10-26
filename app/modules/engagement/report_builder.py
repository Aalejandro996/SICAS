"""Informe automático: arma el cuerpo (JSON canónico) desde los datos de la auditoría y lo imprime en PDF."""
from __future__ import annotations

import hashlib
import io
import json
import os
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from .scoring import RATING_LABEL
from .templates import KINDS, LINES

# Cajas de firma electrónica (PAdES) en la última página: (x1, y1, x2, y2) en puntos, origen abajo-izquierda
SIG_BOX_CONTRALOR = (57, 250, 285, 340)
SIG_BOX_GERENTE = (327, 250, 555, 340)
NAVY = colors.HexColor("#1F3864")
RISK_COLOR = {"ALTO": "#B00020", "MEDIO": "#B8860B", "BAJO": "#4A6FA5"}


def body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def initials_of(full_name: str) -> str:
    """Solo iniciales de nombre y apellido: 'María Eugenia Pérez Gómez' -> 'MP'."""
    parts = [p for p in full_name.replace(".", " ").split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][0].upper()
    first, last = parts[0], parts[-2] if len(parts) >= 4 else parts[-1]
    return (first[0] + last[0]).upper()


def auto_conclusion(modality: str, unit: str, overall: dict, observations: list[dict], preliminary: bool) -> str:
    score = overall.get("final")
    rating = RATING_LABEL.get(overall["rating"], str(overall["rating"]).replace("_", " ").capitalize()).lower()
    n = len(observations)
    by = {r: sum(1 for o in observations if o["risk"] == r) for r in ("ALTO", "MEDIO", "BAJO")}
    head = "Resultado PRELIMINAR de la auditoría" if preliminary else "Como resultado de la auditoría"
    t = f"{head} {modality.lower()} practicada a {unit}, "
    t += (f"la calificación obtenida es {score:.1f}% ({rating}). " if score is not None else "no fue posible calcular una calificación (sin ítems calificados). ")
    t += (f"Se identificaron {n} observaciones ({by['ALTO']} de riesgo alto, {by['MEDIO']} medio y {by['BAJO']} bajo), "
          "cuyas recomendaciones deben atenderse mediante el Plan de Acción Correctiva (PAC). " if n else "No se identificaron observaciones. ")
    if overall.get("exceptions"):
        t += (f"Se registraron {overall['exceptions']} excepciones por información no recibida; constituyen limitaciones al alcance "
              "y se detallan en este informe. ")
    if overall.get("final_method") == "PROMEDIO_FASES":
        t += ("La nota final corresponde al promedio de las fases de levantamiento de información, documentación y "
              "pruebas de campo. ")
    if overall.get("manual_override"):
        t += "La calificación global fue ajustada manualmente por el auditor, con la justificación indicada en este informe."
    return t.strip()


def build_body(*, kind: str, audit: dict, file: dict, unit: dict, team: list[dict], sheets: list[dict], overall: dict,
               observations: list[dict], limitations: list[dict], adjustments: list[dict], evidence: list[dict],
               company: str, version: int, today: date, conclusion: str | None = None, thresholds: dict | None = None) -> dict:
    body = {
        "kind": kind, "version": version, "company": company, "generated_on": today.isoformat(),
        "audit_code": audit["code"], "file_code": file["code"], "title": file["title"],
        "unit": {"code": unit["code"], "name": unit["name"], "kind": unit["kind"]},
        "modality": audit["modality"], "period": {"from": str(file["period_from"]), "to": str(file["period_to"])},
        "objectives": audit["objectives"], "scope": audit["scope"], "procedures": audit.get("procedures") or "",
        "contact": {"name": audit.get("contact_name") or "", "role": audit.get("contact_role") or ""},
        "team": [{"name": t["name"], "initials": t["initials"], "role": t["role"], "system_role": t.get("system_role")} for t in team],
        "sheets": sheets, "overall": overall, "thresholds": thresholds or {},
        "observations": observations, "limitations": limitations, "adjustments": adjustments, "evidence": evidence,
    }
    body["conclusion"] = conclusion or auto_conclusion(audit["modality"], unit["name"], overall, observations, kind == "PREVIO")
    body["conclusion_custom"] = bool(conclusion)
    return body


# ---------------------------------------------------------------------------------------- PDF
def _team_role(t):
    """Rol del integrante en SICAS (Jefe o Auditor); no se usa la función interna del equipo."""
    return t.get("system_role") or "Auditor"


def _num(v):
    return "—" if v is None else f"{float(v):.1f}"


def _signed(v):
    return "—" if v is None else f"{float(v):+.1f}"


def _rating(code):
    return RATING_LABEL.get(code, str(code or "").replace("_", " ").capitalize())


def _label(code):
    return {"PLANIFICACION": "Planificación", "TRABAJO_CAMPO": "Trabajo de campo", "INFORME": "Informe",
            "LEVANTAMIENTO": "Levantamiento de información", "DOCUMENTACION": "Documentación",
            "PRUEBAS_CAMPO": "Pruebas de campo"}.get(code, code or "—")


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def _d(v):
    return str(v or "—")[:16].replace("T", " ")


def _action(code):
    return {"SUBMIT": "Envío a revisión", "RETURN": "Devolución", "APPROVE_JEFE": "Aprobación del Jefe de Auditoría",
            "APPROVE_SIGN_GERENTE": "Aprobación y firma de Gerencia", "APPROVE_SIGN_CONTRALOR": "Aprobación y firma de Contraloría",
            "SEND_PREVIO": "Envío del informe previo"}.get(code, code)


def _p(text, style):
    return Paragraph(escape("" if text is None else str(text)).replace("\n", "<br/>"), style)


def build_pdf(body: dict, state: dict | None = None) -> bytes:
    """
    state = {"status": ..., "initials": {nombre_completo_o_user: iniciales_estampadas_o_None}, "collaborator": {"name","role"}|None,
             "signed": {"CONTRALOR": "nombre", "GERENTE_CI": "nombre"}, "final": bool}
    Sin 'final' se imprime con marca de agua: borrador o informe previo.
    """
    state = state or {}
    final = bool(state.get("final"))
    preliminary = body["kind"] == "PREVIO"
    mark = None if final else ("INFORME PREVIO" if preliminary else "BORRADOR - NO VÁLIDO")
    ss = getSampleStyleSheet()
    body_st = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body_st, fontSize=8, leading=10)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=15, textColor=NAVY, spaceBefore=12, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11.5, textColor=NAVY, spaceBefore=10, spaceAfter=4)
    cell = ParagraphStyle("c", parent=body_st, fontSize=8.5, leading=11)
    code = f"{body['audit_code']} · {'Informe previo' if preliminary else 'Informe final'} v{body['version']}"

    def furniture(canvas, doc):
        canvas.saveState()
        logo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "branding", "seguros_constitucion.png")
        if os.path.exists(logo):
            try:
                canvas.drawImage(ImageReader(logo), 2 * cm, LETTER[1] - 2.0 * cm, width=2.8 * cm, height=1.25 * cm, preserveAspectRatio=True, mask="auto")
            except Exception:
                pass
        if mark:
            canvas.setFillGray(0.9); canvas.setFont("Helvetica-Bold", 58)
            canvas.translate(LETTER[0] / 2, LETTER[1] / 2); canvas.rotate(45); canvas.drawCentredString(0, 0, mark)
            canvas.rotate(-45); canvas.translate(-LETTER[0] / 2, -LETTER[1] / 2)
        canvas.setFillColor(colors.grey); canvas.setFont("Helvetica", 7.5)
        canvas.drawString(2 * cm, 1.2 * cm, f"{body['company']} · Contraloría · {code}")
        canvas.drawRightString(LETTER[0] - 2 * cm, 1.2 * cm, f"Pág. {doc.page}")
        canvas.restoreState()

    def firmas(canvas, doc):
        furniture(canvas, doc)
        canvas.saveState()
        canvas.setFillColor(NAVY); canvas.setFont("Helvetica-Bold", 14); canvas.drawString(57, 735, "FIRMAS")
        canvas.setFillColor(colors.black); canvas.setFont("Helvetica-Bold", 9); canvas.drawString(57, 705, "Auditores (iniciales)")
        x, y = 57, 650
        for t in body["team"]:
            mark_txt = (state.get("initials") or {}).get(t["name"])
            canvas.setStrokeColor(colors.grey); canvas.rect(x, y, 66, 36)
            if mark_txt:
                canvas.setFont("Helvetica-Bold", 16); canvas.drawCentredString(x + 33, y + 12, mark_txt)
            canvas.setFont("Helvetica", 6.5); canvas.drawCentredString(x + 33, y - 9, "Jefe" if "Jefe" in _team_role(t) else "Auditor")
            canvas.drawCentredString(x + 33, y - 17, t["initials"] if not mark_txt else "")
            x += 76
            if x > 520:
                x, y = 57, y - 62
        collab = state.get("collaborator") or {}
        cy = 540
        canvas.setFont("Helvetica-Bold", 9); canvas.drawString(57, cy, "Colaborador de la unidad auditada")
        canvas.setFont("Helvetica", 9)
        canvas.drawString(57, cy - 15, f"Nombre: {collab.get('name') or body['contact']['name'] or '______________________________'}")
        canvas.drawString(57, cy - 29, f"Cargo: {collab.get('role') or body['contact']['role'] or '______________________________'}")
        canvas.line(57, cy - 70, 300, cy - 70); canvas.setFont("Helvetica", 7.5); canvas.drawString(57, cy - 80, "Firma del colaborador")
        canvas.line(330, cy - 70, 450, cy - 70); canvas.drawString(330, cy - 80, "Fecha")
        for (x1, y1, x2, y2), label, key in ((SIG_BOX_CONTRALOR, "Contralor", "CONTRALOR"), (SIG_BOX_GERENTE, "Gerente de Control Interno", "GERENTE_CI")):
            canvas.setStrokeColor(colors.grey); canvas.rect(x1, y1, x2 - x1, y2 - y1)
            canvas.setFont("Helvetica-Bold", 9); canvas.setFillColor(colors.black)
            canvas.drawString(x1, y1 - 14, label)
            canvas.setFont("Helvetica", 8)
            canvas.drawString(x1, y1 - 26, "Firma electrónica")
        canvas.restoreState()

    doc_io = io.BytesIO()
    doc = BaseDocTemplate(doc_io, pagesize=LETTER, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                          title=f"{code} — {body['title']}", author=body["company"], subject="Informe de auditoría")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=furniture),
                          PageTemplate(id="firmas", frames=[Frame(2 * cm, 2 * cm, 200, 50, id="f2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=firmas)])

    def table(data, widths, header=True):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        st = [("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(st)); return t

    hdr = ParagraphStyle("hd", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    s = []
    s += [Paragraph(escape(body["company"]), h2), Paragraph("CONTRALORÍA CORPORATIVA", ParagraphStyle("cc", parent=h2, fontSize=10)), Paragraph("INFORME PREVIO DE AUDITORÍA" if preliminary else "INFORME DE AUDITORÍA", ParagraphStyle("t", parent=h1, fontSize=20)),
          _p(body["title"], h2), Spacer(1, 6)]
    s.append(table([[_p("Auditoría", cell), _p(body["audit_code"], cell), _p("Expediente", cell), _p(body["file_code"], cell)],
                    [_p("Unidad auditada", cell), _p(f"{body['unit']['name']} ({body['unit']['kind'].lower()})", cell), _p("Modalidad", cell), _p(body["modality"].capitalize(), cell)],
                    [_p("Período revisado", cell), _p(f"{body['period']['from']} a {body['period']['to']}", cell), _p("Fecha del informe", cell), _p(body["generated_on"], cell)]],
                   [3 * cm, 5.7 * cm, 3 * cm, 5.3 * cm], header=False))
    s += [Paragraph("1. Objetivo y alcance", h1), _p(body["objectives"], body_st), Spacer(1, 4), _p(body["scope"], body_st)]
    if body["procedures"]:
        s += [Paragraph("Procedimientos aplicados", h2), _p(body["procedures"], body_st)]
    s += [Paragraph("Equipo auditor", h2),
          table([[Paragraph(x, hdr) for x in ("Nombre", "Rol", "Iniciales")]] +
                [[_p(t["name"], cell), _p(_team_role(t), cell), _p(t["initials"], cell)] for t in body["team"]],
                [7.5 * cm, 7 * cm, 3 * cm])]

    s.append(Paragraph("2. Resultados de la evaluación", h1))
    ov = body["overall"]
    final_txt = "—" if ov.get("final") is None else f"{ov['final']:.1f}%"
    phases = ov.get("phase_scores") or []
    if phases:
        rows = [[Paragraph(x, hdr) for x in ("Fase", "Nota", "Calificación", "Estado")]]
        for i, ph in enumerate(phases, 1):
            rows.append([_p(f"{i}. {_label(ph['phase'])}", cell), _p(_num(ph.get("score")), cell), _p(_rating(ph.get("rating")), cell),
                         _p(f"Cerrada {_d(ph.get('closed_at'))}" if ph.get("closed") else "En curso" if ph.get("score") is not None else "Pendiente", cell)])
        method = ("Nota final: promedio simple de las fases 1, 2 y 3" if ov.get("final_method") == "PROMEDIO_FASES"
                  else "Nota vigente (fase en curso)")
        rows.append([_p(method + (" — ajustada manualmente" if ov.get("manual_override") else ""), cell), _p(final_txt.rstrip("%"), cell),
                     _p(_rating(ov.get("rating")), cell), _p("", cell)])
        t = table(rows, [7.5 * cm, 2.5 * cm, 3.5 * cm, 4 * cm])
        t.setStyle(TableStyle([("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8EEF7"))]))
        s += [t, Spacer(1, 4)]
    else:
        s.append(Paragraph(f"<b>Calificación global:</b> {final_txt} · {escape(_rating(ov.get('rating')))}"
                           + (" (ajustada manualmente)" if ov.get("manual_override") else ""), body_st))
    th = body.get("thresholds") or {}
    excelente = th.get("excelente", 90)
    satisfactorio = th.get("satisfactorio", 70)
    aceptable = th.get("aceptable", 60)
    mejora = th.get("mejora", 50)
    s.append(_p(
        f"Escala: Excelente > {excelente}; "
        f"Satisfactorio ≥ {satisfactorio} y ≤ {excelente}; "
        f"Aceptable ≥ {aceptable} y < {satisfactorio}; "
        f"Necesita mejoras ≥ {mejora} y < {aceptable}; "
        f"No satisfactoria < {mejora}.",
        small,
    ))
    if ov.get("manual_override") and body.get("overall_reason"):
        s.append(_p(f"Ajuste manual de la calificación global: {body['overall_reason']}", small))

    ind = body.get("indicators")
    if ind:
        s.append(Paragraph("Cuadro de resultados de la evaluación", h2))
        big = ParagraphStyle("big", parent=cell, fontSize=15, leading=18, fontName="Helvetica-Bold", textColor=NAVY)
        lab = ParagraphStyle("lab", parent=cell, fontSize=7.2, leading=8.6, textColor=colors.HexColor("#444444"))
        for w in ind["worksheets"]:
            score = "—" if w["score"] is None else f"{w['score']:.1f}%"
            values = {i["key"]: i["value"] for i in w["indicators"]}
            head = f"<b>{escape(w['title'] or 'Cédula')}</b> · {_rating(w['rating'])} · Final {score}"
            if "total" in values:
                head += f" · {values['total']} controles · {values.get('respondidas', 0)} respondidos"
            s.append(Paragraph(head, cell))
            cells = [[Paragraph(str(i["value"]), big) for i in w["indicators"]],
                     [Paragraph(escape(i["label"]), lab) for i in w["indicators"]]]
            n = len(w["indicators"]) or 1
            t = Table(cells, colWidths=[doc.width / n] * n)
            t.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3E3")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3E3")),
                ("LINEABOVE", (0, 0), (-1, 0), 2, colors.HexColor("#319C91")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            s += [Spacer(1, 3), t, Spacer(1, 6)]

    s.append(Paragraph("3. Observaciones", h1))
    if not body["observations"]:
        s.append(_p("No se identificaron observaciones.", body_st))
    for o in body["observations"]:
        rows = [[Paragraph(f"<b>Observación {o['n']}</b>: {escape(o['title'])}", ParagraphStyle('x', parent=cell, textColor=colors.white)),
                 Paragraph(f"<b>Riesgo {o['risk']}</b>", ParagraphStyle('y', parent=cell, textColor=colors.white, alignment=2))]]
        for label, key in (("Condición", "condition"), ("Criterio", "criteria"), ("Causa", "cause"), ("Efecto", "effect"), ("Recomendación", "recommendation")):
            if o.get(key):
                rows.append([_p(f"{label}: {o[key]}", cell), ""])
        if not preliminary and o.get("unit_decision"):
            rows.append([_p(f"Respuesta de la unidad ({o['unit_decision']}): {o.get('unit_response') or ''}", cell), ""])
        if not preliminary and o.get("pac_action"):
            rows.append([_p(f"PAC: {o['pac_action']} — Responsable: {o.get('pac_owner') or '—'} — Fecha: {o.get('pac_due') or '—'}", cell), ""])
        t = Table(rows, colWidths=[14.2 * cm, 3.3 * cm])
        st = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(RISK_COLOR[o["risk"]])), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        st += [("SPAN", (0, i), (1, i)) for i in range(1, len(rows))]
        t.setStyle(TableStyle(st)); s += [KeepTogether([t]), Spacer(1, 6)]

    if body.get("observation_changes"):
        s.append(Paragraph("Observaciones modificadas después de su registro original", h2))
        rows = [[Paragraph(x, hdr) for x in ("Obs.", "Registro original", "Rev.", "Fecha / usuario", "Campos", "Motivo")]]
        for oc in body["observation_changes"]:
            orig = oc["original"]
            for i, ch in enumerate(oc["changes"]):
                rows.append([_p(oc["n"] if i == 0 else "", cell),
                             _p(f"{orig.get('title') or ''} — {orig.get('condition') or ''} (riesgo {orig.get('risk') or '—'})" if i == 0 else "", cell),
                             _p(ch["revision"], cell), _p(f"{_d(ch['date'])} · {ch.get('user') or '—'}", cell),
                             _p(", ".join(ch["fields"]), cell), _p(ch["reason"], cell)])
        s.append(table(rows, [1 * cm, 5 * cm, 1 * cm, 3 * cm, 2.6 * cm, 4.9 * cm]))

    s.append(Paragraph("4. Limitaciones al alcance (información no recibida)", h1))
    if body["limitations"]:
        s.append(table([[Paragraph(x, hdr) for x in ("Cédula", "Referencia", "Detalle de la excepción")]] +
                       [[_p(l["sheet"], cell), _p(l["ref"], cell), _p(l["detail"], cell)] for l in body["limitations"]], [4.5 * cm, 3.5 * cm, 9.5 * cm]))
    else:
        s.append(_p("No se registraron excepciones por información no recibida.", body_st))
    if body["adjustments"]:
        s += [Paragraph("5. Ajustes manuales de calificación (criterio del auditor)", h1),
              table([[Paragraph(x, hdr) for x in ("Cédula", "Referencia", "Auto", "Final", "Justificación")]] +
                    [[_p(a["sheet"], cell), _p(a["ref"], cell), _p("—" if a["auto"] is None else f"{a['auto']:.1f}", cell), _p(f"{a['final']:.1f}", cell), _p(a["reason"], cell)]
                     for a in body["adjustments"]], [3.2 * cm, 2.8 * cm, 2 * cm, 1.7 * cm, 7.8 * cm])]
    if body.get("score_history") is not None:
        s.append(Paragraph("6. Evolución de la calificación por fase", h1))
        if not body["score_history"]:
            s.append(_p("No hay instantáneas de fase registradas para esta auditoría.", body_st))
        else:
            rows = [[Paragraph(x, hdr) for x in ("Fecha", "Fase / evento", "Nota", "Nivel", "Variación", "Usuario", "Motivo")]]
            for hst in body["score_history"]:
                rows.append([_p(_d(hst["date"]), cell), _p(f"{_label(hst['phase'])} · {hst['event']}", cell), _p(_num(hst["score"]), cell),
                             _p(_rating(hst["rating"]), cell), _p(_signed(hst["delta"]), cell), _p(hst.get("user") or "—", cell),
                             _p(hst.get("reason") or "—", cell)])
            s.append(table(rows, [2.2 * cm, 3.6 * cm, 1.4 * cm, 2.4 * cm, 1.6 * cm, 2.2 * cm, 4.1 * cm]))
            changed = [(hst, it) for hst in body["score_history"] for it in hst["changed_items"]]
            if changed:
                s.append(Paragraph("Ítems que originaron los ajustes", h2))
                rows = [[Paragraph(x, hdr) for x in ("Fase", "Cédula", "Ref.", "Antes", "Después", "Motivo / sustento")]]
                rows += [[_p(_label(hst["phase"]), cell), _p(it["sheet"], cell), _p(it["ref"], cell), _p(_num(it["before"]), cell),
                          _p(_num(it["after"]), cell), _p(it["reason"] or "—", cell)] for hst, it in changed]
                s.append(table(rows, [2.4 * cm, 3.4 * cm, 2 * cm, 1.4 * cm, 1.6 * cm, 6.7 * cm]))
            added = [(hst, e) for hst in body["score_history"] for e in hst["evidence_added"]]
            if added:
                s.append(_p("Evidencia incorporada entre fases: " + "; ".join(
                    f"{_label(hst['phase'])}: {e['filename']}" + (f" (anexo {e['n']})" if e.get("n") else "") for hst, e in added), small))
            versions = sorted({hst["rule_version"] for hst in body["score_history"] if hst.get("rule_version")})
            if versions:
                s.append(_p("Regla de cálculo aplicada: " + ", ".join(versions), small))

    if body.get("review_history") is not None:
        s.append(Paragraph("7. Revisión, devoluciones y aprobaciones", h1))
        live = (state.get("transitions") or [])
        history = body["review_history"] + [
            {"date": str(t.get("created_at")), "action": _action(t["action"]), "report_version": t.get("report_version"),
             "user": t.get("actor_username"), "comment": t.get("comment") or "", "points": []}
            for t in live if not any(h.get("date") == _iso(t.get("created_at")) and h.get("code") == t["action"] for h in body["review_history"])
        ]
        if not history:
            s.append(_p("Sin decisiones de revisión registradas.", body_st))
        else:
            rows = [[Paragraph(x, hdr) for x in ("Fecha", "Versión", "Decisión", "Usuario", "Comentario y puntos")]]
            live_points = {pt.get("id"): pt for pt in state.get("review_points") or []}
            for rv in history:
                for pt in rv.get("points") or []:
                    cur = live_points.get(pt.get("id"))
                    if cur:  # el estado de atención vigente prevalece sobre el del contenido generado
                        pt["status"], pt["attended_note"] = cur["status"], cur.get("attended_note") or ""
                detail = rv["comment"] + "".join(
                    f"\n• {pt['target']}: {pt['description']} [{pt['status']}]" + (f" — {pt['attended_note']}" if pt.get("attended_note") else "")
                    for pt in rv.get("points") or [])
                rows.append([_p(_d(rv["date"]), cell), _p(f"v{rv.get('report_version') or '—'}", cell), _p(rv["action"], cell),
                             _p(rv.get("user") or "—", cell), _p(detail or "—", cell)])
            s.append(table(rows, [2.4 * cm, 1.4 * cm, 3.6 * cm, 2.4 * cm, 7.7 * cm]))
        for ro in body.get("reopenings") or []:
            s.append(_p(f"Reapertura autorizada de la versión v{ro['version']} ({_d(ro['date'])}, {ro.get('user') or '—'}): {ro['reason']}", small))

    s += [Paragraph("8. Conclusión" if body.get("review_history") is not None else "6. Conclusión", h1), _p(body["conclusion"], body_st)]
    s.append(_p(f"Identificación del documento: {code} · revisión de contenido {body.get('revision', 1)}"
                + (f" · SHA-256 {state['body_sha256']}" if state.get("body_sha256") else ""), small))
    s.append(Paragraph("Anexo de evidencias", h1))
    if body["evidence"]:
        s.append(table([[Paragraph(x, hdr) for x in ("N°", "Archivo", "Descripción", "Huella SHA-256")]] +
                       [[_p(e["n"], cell), _p(e["filename"], cell), _p(e["description"], cell), _p(e["sha256"][:16] + "…", cell)] for e in body["evidence"]],
                       [1.2 * cm, 6 * cm, 6.3 * cm, 4 * cm]))
    else:
        s.append(_p("Sin evidencias adjuntas.", body_st))
    s += [NextPageTemplate("firmas"), PageBreak(), Spacer(1, 1)]
    doc.build(s)
    return doc_io.getvalue()
