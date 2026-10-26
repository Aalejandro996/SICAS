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


MAX_PAGES = 15
RISK_ORDER = {"ALTO": 0, "MEDIO": 1, "BAJO": 2}


def build_pdf(body: dict, state: dict | None = None) -> bytes:
    """
    Informe en seis secciones: Introducción, Objetivo y alcance, Resultados de la evaluación,
    Limitaciones, Conclusión y Anexo de evidencias, más la hoja de firmas.

    No supera MAX_PAGES páginas: si el contenido no cabe, se imprime con un nivel de detalle
    progresivamente más compacto (los textos completos siguen disponibles en SICAS).

    state = {"initials": {...}, "collaborator": {"name","role"}|None, "final": bool, "transitions": [...],
             "review_points": [...], "body_sha256": str}
    Sin 'final' se imprime con marca de agua: borrador o informe previo.
    """
    pdf = pages = None
    for level in range(5):
        pdf, pages = _render(body, state or {}, level)
        if pages <= MAX_PAGES:
            break
    return pdf


def page_count(body: dict, state: dict | None = None) -> int:
    """Páginas del informe tal como se imprime (para pruebas y controles)."""
    for level in range(5):
        _, pages = _render(body, state or {}, level)
        if pages <= MAX_PAGES:
            return pages
    return pages


def _cut(text, n):
    text = "" if text is None else str(text)
    return text if n is None or len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _render(body: dict, state: dict, level: int) -> tuple[bytes, int]:
    final = bool(state.get("final"))
    preliminary = body["kind"] == "PREVIO"
    mark = None if final else ("INFORME PREVIO" if preliminary else "BORRADOR - NO VÁLIDO")
    ss = getSampleStyleSheet()
    fs = (9.5, 9, 8.5, 8, 8)[level]
    body_st = ParagraphStyle("b", parent=ss["BodyText"], fontSize=fs, leading=fs + 3.2)
    small = ParagraphStyle("s", parent=body_st, fontSize=7.5, leading=9.5)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=14, textColor=NAVY, spaceBefore=10 if level < 2 else 6, spaceAfter=5)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=11, textColor=NAVY, spaceBefore=8 if level < 2 else 4, spaceAfter=3)
    cell = ParagraphStyle("c", parent=body_st, fontSize=fs - 1, leading=fs + 1.6)
    doc_code = body.get("report_code") or body["audit_code"]
    code = f"{doc_code} · {'Informe previo' if preliminary else 'Informe final'} v{body['version']}"

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
              ("TOPPADDING", (0, 0), (-1, -1), 2 if level >= 2 else 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 2 if level >= 2 else 3)]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
        t.setStyle(TableStyle(st)); return t

    def capped(rows, limit, what):
        """Primeras `limit` filas y una nota con las omitidas (el detalle completo queda en SICAS)."""
        if limit is None or len(rows) <= limit:
            return rows, None
        return rows[:limit], _p(f"Se muestran {limit} de {len(rows)} {what}; el detalle completo está disponible en SICAS.", small)

    hdr = ParagraphStyle("hd", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    ov = body["overall"]
    final_txt = "—" if ov.get("final") is None else f"{ov['final']:.1f}%"
    s = []

    # ------------------------------------------------------------ portada breve
    s += [Paragraph(escape(body["company"]), h2), Paragraph("CONTRALORÍA CORPORATIVA", ParagraphStyle("cc", parent=h2, fontSize=10)),
          Paragraph("INFORME PREVIO DE AUDITORÍA" if preliminary else "INFORME DE AUDITORÍA", ParagraphStyle("t", parent=h1, fontSize=19)),
          _p(body["title"], h2), Spacer(1, 4)]
    s.append(table([[_p("Informe N°", cell), _p(doc_code, cell), _p("Fecha del informe", cell), _p(body["generated_on"], cell)],
                    [_p("Auditoría", cell), _p(body["audit_code"], cell), _p("Expediente", cell), _p(body["file_code"], cell)],
                    [_p("Unidad auditada", cell), _p(f"{body['unit']['name']} ({body['unit']['kind'].lower()})", cell), _p("Modalidad", cell), _p(body["modality"].capitalize(), cell)],
                    [_p("Período revisado", cell), _p(f"{body['period']['from']} a {body['period']['to']}", cell), _p("Calificación", cell), _p(f"{final_txt} · {_rating(ov.get('rating'))}", cell)]],
                   [3 * cm, 5.7 * cm, 3 * cm, 5.3 * cm], header=False))

    # ------------------------------------------------------------ 1. Introducción
    n_obs = len(body["observations"])
    by_risk = {r: sum(1 for o in body["observations"] if o["risk"] == r) for r in ("ALTO", "MEDIO", "BAJO")}
    intro = (f"La Contraloría Corporativa de {body['company']} practicó la auditoría {body['modality'].lower()} "
             f"{body['audit_code']} a la unidad {body['unit']['name']}, correspondiente al período del {body['period']['from']} "
             f"al {body['period']['to']}. Este {'informe previo' if preliminary else 'informe'} ({doc_code}) presenta el objetivo y "
             f"alcance del trabajo, los resultados de la evaluación con {n_obs} hallazgo(s) "
             f"({by_risk['ALTO']} de riesgo alto, {by_risk['MEDIO']} medio y {by_risk['BAJO']} bajo), las limitaciones al alcance, "
             f"la conclusión y el anexo de evidencias.")
    s += [Paragraph("1. Introducción", h1), _p(intro, body_st), Spacer(1, 4),
          table([[Paragraph(x, hdr) for x in ("Equipo auditor", "Rol", "Iniciales")]] +
                [[_p(t["name"], cell), _p(_team_role(t), cell), _p(t["initials"], cell)] for t in body["team"]],
                [7.5 * cm, 7 * cm, 3 * cm])]

    # ------------------------------------------------------------ 2. Objetivo y alcance
    s += [Paragraph("2. Objetivo y alcance", h1), Paragraph("<b>Objetivo.</b> " + escape(_cut(body["objectives"], (None, None, 1500, 900, 600)[level])), body_st),
          Spacer(1, 3), Paragraph("<b>Alcance.</b> " + escape(_cut(body["scope"], (None, None, 1500, 900, 600)[level])), body_st)]
    if body["procedures"]:
        s += [Spacer(1, 3), Paragraph("<b>Procedimientos aplicados.</b> " + escape(_cut(body["procedures"], (None, None, 1200, 700, 400)[level])), body_st)]

    # ------------------------------------------------------------ 3. Resultados de la evaluación
    s.append(Paragraph("3. Resultados de la evaluación", h1))
    s.append(Paragraph("3.1 Calificación", h2))
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
        s += [t, Spacer(1, 3)]
    else:
        s.append(Paragraph(f"<b>Calificación global:</b> {final_txt} · {escape(_rating(ov.get('rating')))}"
                           + (" (ajustada manualmente)" if ov.get("manual_override") else ""), body_st))
    th = body.get("thresholds") or {}
    excelente, satisfactorio = th.get("excelente", 90), th.get("satisfactorio", 70)
    aceptable, mejora = th.get("aceptable", 60), th.get("mejora", 50)
    if th.get("scale") == "TRES_NIVELES":
        s.append(_p(f"Escala: Excelente > {th['excelente']}%; Aceptable > {th['aceptable']}% y ≤ {th['excelente']}%; "
                    f"No satisfactoria ≤ {th['aceptable']}%.", small))
    else:
        s.append(_p(f"Escala: Excelente > {excelente}; Satisfactorio ≥ {satisfactorio} y ≤ {excelente}; Aceptable ≥ {aceptable} y < {satisfactorio}; "
                    f"Necesita mejoras ≥ {mejora} y < {aceptable}; No satisfactoria < {mejora}.", small))
    if ov.get("manual_override") and body.get("overall_reason"):
        s.append(_p(f"Ajuste manual de la calificación global: {body['overall_reason']}", small))

    ind = body.get("indicators")
    if ind and ind.get("worksheets"):
        s.append(Paragraph("3.2 Cuadro de resultados de la evaluación", h2))
        big = ParagraphStyle("big", parent=cell, fontSize=15 if level < 2 else 13, leading=18 if level < 2 else 15, fontName="Helvetica-Bold", textColor=NAVY)
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
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3E3")), ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3E3")),
                ("LINEABOVE", (0, 0), (-1, 0), 2, colors.HexColor("#319C91")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]))
            s += [Spacer(1, 2), t, Spacer(1, 4)]

    s.append(Paragraph("3.3 Hallazgos", h2))
    observations = sorted(body["observations"], key=lambda o: (RISK_ORDER.get(o["risk"], 3), o["n"]))
    if not observations:
        s.append(_p("No se identificaron observaciones.", body_st))
    elif level <= 1:
        limits = {"condition": (None, 900)[level], "criteria": (None, 400)[level], "cause": (None, 500)[level],
                  "effect": (None, 500)[level], "recommendation": (None, 700)[level]}
        for o in observations:
            rows = [[Paragraph(f"<b>Hallazgo {o['n']}</b>: {escape(o['title'])}", ParagraphStyle('x', parent=cell, textColor=colors.white)),
                     Paragraph(f"<b>Riesgo {o['risk']}</b>", ParagraphStyle('y', parent=cell, textColor=colors.white, alignment=2))]]
            for label, key in (("Condición", "condition"), ("Criterio", "criteria"), ("Causa", "cause"), ("Efecto", "effect"), ("Recomendación", "recommendation")):
                if o.get(key):
                    rows.append([_p(f"{label}: {_cut(o[key], limits[key])}", cell), ""])
            if not preliminary and o.get("unit_decision"):
                rows.append([_p(f"Respuesta de la unidad ({o['unit_decision']}): {_cut(o.get('unit_response') or '', limits['cause'])}", cell), ""])
            if not preliminary and o.get("pac_action"):
                rows.append([_p(f"PAC: {_cut(o['pac_action'], limits['cause'])} — Responsable: {o.get('pac_owner') or '—'} — Fecha: {o.get('pac_due') or '—'}", cell), ""])
            t = Table(rows, colWidths=[14.2 * cm, 3.3 * cm])
            st = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(RISK_COLOR[o["risk"]])), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]
            st += [("SPAN", (0, i), (1, i)) for i in range(1, len(rows))]
            t.setStyle(TableStyle(st)); s += [KeepTogether([t]) if level == 0 else t, Spacer(1, 5)]
    else:
        # Formato tabular: cada hallazgo en una fila con condición y recomendación resumidas.
        cut_c, cut_r = {2: (420, 380), 3: (220, 220), 4: (140, 140)}[level]
        rows = [[Paragraph(x, hdr) for x in ("N°", "Riesgo", "Hallazgo y condición", "Recomendación")]]
        rows += [[_p(o["n"], cell), _p(o["risk"], cell),
                  Paragraph(f"<b>{escape(o['title'])}</b><br/>{escape(_cut(o['condition'], cut_c))}", cell),
                  _p(_cut(o.get("recommendation") or "", cut_r), cell)] for o in observations]
        rows, note = capped(rows, {2: None, 3: None, 4: 31}[level], "hallazgos (ordenados por riesgo)")
        t = table(rows, [0.9 * cm, 1.4 * cm, 8.4 * cm, 6.8 * cm])
        t.setStyle(TableStyle([("TEXTCOLOR", (1, i), (1, i), colors.HexColor(RISK_COLOR.get(observations[i - 1]["risk"], "#000000")))
                               for i in range(1, len(rows))]))
        s.append(t)
        if note:
            s.append(note)
        s.append(_p("Criterio, causa y efecto de cada hallazgo se registran en SICAS y en el Plan de Acción Correctiva.", small))

    # trazabilidad dentro de los resultados (compacta según el nivel)
    trace = []
    if body["adjustments"]:
        rows = [[Paragraph(x, hdr) for x in ("Cédula", "Ref.", "Auto", "Final", "Justificación")]] + \
               [[_p(a_["sheet"], cell), _p(a_["ref"], cell), _p(_num(a_["auto"]), cell), _p(_num(a_["final"]), cell),
                 _p(_cut(a_["reason"], (None, 300, 200, 120, 80)[level]), cell)] for a_ in body["adjustments"]]
        rows, note = capped(rows, (None, None, 16, 9, 6)[level], "ajustes manuales")
        trace += [Paragraph("Ajustes manuales de calificación", ParagraphStyle("h3", parent=h2, fontSize=10)), table(rows, [3.2 * cm, 2.6 * cm, 1.6 * cm, 1.6 * cm, 8.5 * cm])]
        trace += [note] if note else []
    if body.get("score_history"):
        rows = [[Paragraph(x, hdr) for x in ("Fecha", "Fase / evento", "Nota", "Variación", "Motivo")]] + \
               [[_p(_d(h_["date"]), cell), _p(f"{_label(h_['phase'])} · {h_['event']}", cell), _p(_num(h_["score"]), cell),
                 _p(_signed(h_["delta"]), cell), _p(_cut(h_.get("reason") or "—", (None, 200, 120, 80, 60)[level]), cell)] for h_ in body["score_history"]]
        rows, note = capped(rows, (None, None, 13, 9, 7)[level], "registros de evolución")
        trace += [Paragraph("Evolución de la calificación por fase", ParagraphStyle("h3", parent=h2, fontSize=10)),
                  table(rows, [2.4 * cm, 4.6 * cm, 1.5 * cm, 1.8 * cm, 7.2 * cm])]
        trace += [note] if note else []
        changed = [(h_, it) for h_ in body["score_history"] for it in h_["changed_items"]]
        if changed and level <= 2:
            rows = [[Paragraph(x, hdr) for x in ("Fase", "Ref.", "Antes", "Después", "Sustento")]] + \
                   [[_p(_label(h_["phase"]), cell), _p(it["ref"], cell), _p(_num(it["before"]), cell), _p(_num(it["after"]), cell),
                     _p(_cut(it["reason"] or "—", (None, 160, 90)[level]), cell)] for h_, it in changed]
            rows, note = capped(rows, (None, 40, 15)[level], "ítems ajustados")
            trace += [Paragraph("Ítems que originaron los ajustes", ParagraphStyle("h3", parent=h2, fontSize=10)),
                      table(rows, [3 * cm, 2.2 * cm, 1.5 * cm, 1.7 * cm, 9.1 * cm])]
            trace += [note] if note else []
        elif changed:
            trace.append(_p(f"{len(changed)} ítem(s) cambiaron de calificación entre fases; el detalle consta en la bitácora del expediente.", small))
    if body.get("observation_changes"):
        total = sum(len(oc["changes"]) for oc in body["observation_changes"])
        if level <= 1:
            rows = [[Paragraph(x, hdr) for x in ("Hall.", "Registro original", "Rev.", "Campos", "Motivo")]]
            for oc in body["observation_changes"]:
                orig = oc["original"]
                for i, ch in enumerate(oc["changes"]):
                    rows.append([_p(oc["n"] if i == 0 else "", cell),
                                 _p(_cut(f"{orig.get('title') or ''} — {orig.get('condition') or ''} (riesgo {orig.get('risk') or '—'})", (None, 260)[level]) if i == 0 else "", cell),
                                 _p(ch["revision"], cell), _p(", ".join(ch["fields"]), cell), _p(_cut(ch["reason"], (None, 200)[level]), cell)])
            trace += [Paragraph("Hallazgos modificados después de su registro original", ParagraphStyle("h3", parent=h2, fontSize=10)),
                      table(rows, [1.1 * cm, 6 * cm, 1 * cm, 3 * cm, 6.4 * cm])]
        else:
            trace.append(_p(f"{len(body['observation_changes'])} hallazgo(s) se modificaron después de su registro original "
                            f"({total} revisión(es) con motivo); el registro original y cada cambio constan en SICAS.", small))
    if trace:
        s += [Paragraph("3.4 Ajustes y trazabilidad de la calificación", h2)] + trace

    # ------------------------------------------------------------ 4. Limitaciones
    s.append(Paragraph("4. Limitaciones al alcance", h1))
    if body["limitations"]:
        rows = [[Paragraph(x, hdr) for x in ("Cédula", "Referencia", "Información no recibida")]] + \
               [[_p(l_["sheet"], cell), _p(l_["ref"], cell), _p(_cut(l_["detail"], (None, 400, 220, 140, 90)[level]), cell)] for l_ in body["limitations"]]
        rows, note = capped(rows, (None, None, 25, 15, 10)[level], "limitaciones")
        s.append(table(rows, [4.5 * cm, 3.2 * cm, 9.8 * cm]))
        if note:
            s.append(note)
    else:
        s.append(_p("No se registraron excepciones por información no recibida.", body_st))

    # ------------------------------------------------------------ 5. Conclusión
    s += [Paragraph("5. Conclusión", h1), _p(body["conclusion"], body_st), Spacer(1, 3),
          _p(f"Identificación del documento: {code} · revisión de contenido {body.get('revision', 1)}"
             + (f" · SHA-256 {state['body_sha256']}" if state.get("body_sha256") else ""), small)]

    # ------------------------------------------------------------ 6. Anexo de evidencias
    s.append(Paragraph("6. Anexo de evidencias", h1))
    if body["evidence"]:
        rows = [[Paragraph(x, hdr) for x in ("N°", "Archivo", "Descripción", "Huella SHA-256")]] + \
               [[_p(e["n"], cell), _p(_cut(e["filename"], (None, 90, 70, 50, 40)[level]), cell),
                 _p(_cut(e["description"], (None, 200, 120, 70, 50)[level]), cell), _p(e["sha256"][:16] + "…", cell)] for e in body["evidence"]]
        rows, note = capped(rows, (None, None, 60, 35, 20)[level], "evidencias")
        s.append(table(rows, [1.2 * cm, 6 * cm, 6.3 * cm, 4 * cm]))
        if note:
            s.append(note)
    else:
        s.append(_p("Sin evidencias adjuntas.", body_st))
    review = _review_rows(body, state)
    if review:
        rows = [[Paragraph(x, hdr) for x in ("Fecha", "Versión", "Decisión", "Usuario", "Comentario y puntos")]] + \
               [[_p(_d(rv["date"]), cell), _p(f"v{rv.get('report_version') or '—'}", cell), _p(rv["action"], cell),
                 _p(rv.get("user") or "—", cell), _p(_cut(rv["detail"] or "—", (None, 500, 250, 140, 90)[level]), cell)] for rv in review]
        rows, note = capped(rows, (None, None, 15, 10, 6)[level], "decisiones de revisión")
        s += [Paragraph("Registro de revisión y aprobación", h2), table(rows, [2.4 * cm, 1.4 * cm, 3.6 * cm, 2.4 * cm, 7.7 * cm])]
        if note:
            s.append(note)
    for ro in body.get("reopenings") or []:
        s.append(_p(f"Reapertura autorizada de la versión v{ro['version']} ({_d(ro['date'])}, {ro.get('user') or '—'}): {_cut(ro['reason'], 300)}", small))

    s += [NextPageTemplate("firmas"), PageBreak(), Spacer(1, 1)]
    doc.build(s)
    return doc_io.getvalue(), doc.page


def actor_label(t: dict) -> str | None:
    """Usuario de una decisión de revisión; si actuó un suplente, también el titular («en nombre de»)."""
    user = t.get("actor_username")
    return f"{user or '—'} (suplente, en nombre de {t['on_behalf_of']})" if t.get("on_behalf_of") else user


def _review_rows(body: dict, state: dict) -> list[dict]:
    """Decisiones de revisión del contenido generado más las registradas después (estado vigente de los puntos)."""
    if body.get("review_history") is None:
        return []
    live = state.get("transitions") or []
    history = [dict(h) for h in body["review_history"]] + [
        {"date": str(t.get("created_at")), "action": _action(t["action"]), "report_version": t.get("report_version"),
         "user": actor_label(t), "comment": t.get("comment") or "", "points": []}
        for t in live if not any(h.get("date") == _iso(t.get("created_at")) and h.get("code") == t["action"] for h in body["review_history"])
    ]
    live_points = {pt.get("id"): pt for pt in state.get("review_points") or []}
    for rv in history:
        points = []
        for pt in rv.get("points") or []:
            pt = dict(pt)
            cur = live_points.get(pt.get("id"))
            if cur:  # el estado de atención vigente prevalece sobre el del contenido generado
                pt["status"], pt["attended_note"] = cur["status"], cur.get("attended_note") or ""
            points.append(pt)
        rv["detail"] = rv["comment"] + "".join(
            f"\n• {pt['target']}: {pt['description']} [{pt['status']}]" + (f" — {pt['attended_note']}" if pt.get("attended_note") else "")
            for pt in points)
    return history
