"""PDF del informe general de auditorías: introducción, objetivos, alcance, contenido, conclusión y firmas.

No supera MAX_PAGES páginas: si el contenido no cabe, se imprime con un nivel de detalle progresivamente más
compacto (el detalle completo de cada auditoría sigue disponible en SICAS).
"""
from __future__ import annotations

import io
import os
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

from app.modules.engagement.scoring import RATING_LABEL

from .content import KIND_LABEL, PHASE_LABEL, SITUATION_LABEL

MAX_PAGES = 15
NAVY = colors.HexColor("#1F3864")
SITUATION_COLOR = {"CRITICA": "#F8D4D4", "ATENCION": "#FDE4C8", "ACEPTABLE": "#FFF1C2", "FAVORABLE": "#D7F0DF", "SIN_CALIFICAR": "#ECEFF4"}
RISK_LABEL = {"ALTO": "Alto", "MEDIO": "Medio", "BAJO": "Bajo"}
MARK = {"DRAFT": "BORRADOR", "RETURNED": "BORRADOR", "IN_REVIEW": "EN REVISIÓN"}
# Detalle por nivel: hallazgos por auditoría, largo de la condición, largo del criterio normativo, auditorías con detalle.
LEVELS = ((6, 360, None, None), (4, 200, 600, None), (3, 0, 380, None), (2, 0, 240, 40), (1, 0, 160, 25), (0, 0, 120, 15))


def _pct(v):
    return "—" if v is None else f"{float(v):.1f} %"


def _rating(code):
    return RATING_LABEL.get(code, str(code or "—").replace("_", " ").capitalize())


def _cut(text, n):
    text = " ".join(str(text or "").split())
    return text if not n or len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _date(v):
    v = str(v or "")
    return f"{v[8:10]}/{v[5:7]}/{v[:4]}" if len(v) >= 10 else (v or "—")


def build_pdf(body: dict, state: dict) -> bytes:
    """state: status, body_sha256, auditor {name, role, date, image}, jefe {name, date, image}|None, acks [{name, role, date}]."""
    pdf = None
    for level in range(len(LEVELS)):
        pdf, pages = _render(body, state, level)
        if pages <= MAX_PAGES:
            break
    return pdf


def page_count(body: dict, state: dict) -> int:
    for level in range(len(LEVELS)):
        _, pages = _render(body, state, level)
        if pages <= MAX_PAGES:
            return pages
    return pages


def _render(body: dict, state: dict, level: int) -> tuple[bytes, int]:
    obs_n, cond_n, crit_n, audits_n = LEVELS[level]
    ss = getSampleStyleSheet()
    fs = (9.5, 9, 9, 8.5, 8, 8)[level]
    text = ParagraphStyle("b", parent=ss["BodyText"], fontSize=fs, leading=fs + 3)
    small = ParagraphStyle("s", parent=text, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#3A4A60"))
    cell = ParagraphStyle("c", parent=text, fontSize=fs - 1, leading=fs + 1.5)
    hdr = ParagraphStyle("hd", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=13.5, textColor=NAVY, spaceBefore=9 if level < 3 else 5, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=10.5, textColor=NAVY, spaceBefore=6 if level < 3 else 3, spaceAfter=3)
    P = lambda t, st=cell: Paragraph(escape("" if t is None else str(t)).replace("\n", "<br/>"), st)
    mark = MARK.get(state.get("status"))
    k = body["kpis"]

    def furniture(canvas, doc):
        canvas.saveState()
        logo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "branding", "seguros_constitucion.png")
        if os.path.exists(logo):
            try:
                canvas.drawImage(ImageReader(logo), 2 * cm, LETTER[1] - 1.9 * cm, width=2.6 * cm, height=1.15 * cm, preserveAspectRatio=True, mask="auto")
            except Exception:  # noqa: BLE001
                pass
        if mark:
            canvas.setFillGray(0.9); canvas.setFont("Helvetica-Bold", 58)
            canvas.translate(LETTER[0] / 2, LETTER[1] / 2); canvas.rotate(45); canvas.drawCentredString(0, 0, mark)
            canvas.rotate(-45); canvas.translate(-LETTER[0] / 2, -LETTER[1] / 2)
        canvas.setFillColor(colors.grey); canvas.setFont("Helvetica", 7.5)
        canvas.drawString(2 * cm, 1.2 * cm, f"{body['company']} · Contraloría · Informe general {body['code']} (rev. {body.get('revision', 1)})")
        canvas.drawRightString(LETTER[0] - 2 * cm, 1.2 * cm, f"Pág. {doc.page}")
        canvas.restoreState()

    def table(data, widths, header=True, shade=None):
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        st = [("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B9C4D6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        if header:
            st += [("BACKGROUND", (0, 0), (-1, 0), NAVY)]
        for i, c in (shade or {}).items():
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(c)))
        t.setStyle(TableStyle(st))
        return t

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.1 * cm, bottomMargin=1.9 * cm,
                            title=f"Informe general {body['code']} — {body['title']}", author=body["company"], subject="Informe general de auditorías")
    W = doc.width
    s = [Paragraph(escape(body["company"]), h2), Paragraph("CONTRALORÍA CORPORATIVA", ParagraphStyle("cc", parent=h2, fontSize=9.5)),
         Paragraph("INFORME GENERAL DE AUDITORÍAS", ParagraphStyle("t", parent=h1, fontSize=18)), P(body["title"], h2), Spacer(1, 3)]
    author = body.get("author") or {}
    s.append(table([[P("Informe N°"), P(body["code"]), P("Fecha de emisión"), P(_date(body["generated_on"]))],
                    [P("Auditorías"), P(k["audits"]), P("Unidades / sucursales"), P(k["units"])],
                    [P("Período revisado"), P(f"{_date(body['period']['from'])} a {_date(body['period']['to'])}"), P("Calificación promedio"), P(_pct(k["avg_score"]))],
                    [P("Elaborado por"), P(f"{author.get('name', '—')} ({author.get('role', 'Auditor')})"), P("Revisión"), P(body.get("revision", 1))]],
                   [W * 0.2, W * 0.32, W * 0.24, W * 0.24], header=False))

    # 1. Introducción
    s += [Paragraph("1. Introducción", h1), P(body["introduction"], text)]
    # 2. Objetivos
    s += [Paragraph("2. Objetivos", h1)] + [P(f"• {o}", text) for o in body["objectives"]]
    # 3. Alcance
    s += [Paragraph("3. Alcance", h1), P(body["scope"], text), Spacer(1, 4)]
    rows = [[Paragraph(x, hdr) for x in ("Auditoría", "Unidad / sucursal", "Tipo", "Fase", "Período", "Calificación")]]
    for a in body["audits"]:
        rows.append([P(a["code"]), P(a["unit"]), P(KIND_LABEL.get(a["audit_kind"], a["audit_kind"] or "Sistemas")),
                     P(PHASE_LABEL.get(a["phase"], a["phase"])), P(f"{_date(a['period']['from'])} a {_date(a['period']['to'])}"),
                     P(f"{_pct(a['score'])} · {_rating(a['rating'])}" if a["score"] is not None else "Sin calificar")])
    s.append(table(rows, [W * x for x in (0.17, 0.22, 0.12, 0.12, 0.2, 0.17)]))

    # 4. Contenido
    s.append(Paragraph("4. Contenido", h1))
    s.append(Paragraph("4.1 Situación actual de la organización", h2))
    br, bs = k["by_risk"], k["by_situation"]
    s.append(table([[Paragraph(x, hdr) for x in ("Calificación promedio", "Hallazgos", "Riesgo alto", "Riesgo medio", "Riesgo bajo", "Acciones PAC abiertas", "Limitaciones")],
                    [P(_pct(k["avg_score"])), P(k["observations"]), P(br["ALTO"]), P(br["MEDIO"]), P(br["BAJO"]), P(k["pac_open"]), P(k["limitations"])]],
                   [W / 7] * 7))
    s += [Spacer(1, 3), P("Situación de las unidades: " + ", ".join(f"{bs[x]} {SITUATION_LABEL[x].lower()}" for x in bs) + ". Regla: crítica con 3 o más "
                          "hallazgos de riesgo alto o calificación menor a 50 %; requiere atención con algún hallazgo de riesgo alto o calificación "
                          "menor a 70 %; aceptable con hallazgos de riesgo medio o calificación menor a 85 %; favorable en otro caso; sin calificar si la "
                          "auditoría aún no tiene calificación ni hallazgos.", small), Spacer(1, 3)]
    rows, shade = [[Paragraph(x, hdr) for x in ("Unidad / sucursal", "Auditorías", "Calificación", "Alto", "Medio", "Bajo", "Situación")]], {}
    for i, u in enumerate(body["units"], 1):
        shade[i] = SITUATION_COLOR[u["situation"]]
        rows.append([P(u["unit"]), P(", ".join(u["audits"])), P(_pct(u["score"])), P(u["by_risk"]["ALTO"]), P(u["by_risk"]["MEDIO"]),
                     P(u["by_risk"]["BAJO"]), P(SITUATION_LABEL[u["situation"]])])
    s.append(table(rows, [W * x for x in (0.24, 0.24, 0.12, 0.08, 0.08, 0.08, 0.16)], shade=shade))

    s.append(Paragraph("4.2 Resultados por auditoría", h2))
    detail = body["audits"]
    if audits_n and len(detail) > audits_n:
        order = {"CRITICA": 0, "ATENCION": 1, "ACEPTABLE": 2, "FAVORABLE": 3, "SIN_CALIFICAR": 4}
        detail = sorted(detail, key=lambda a: (order[a["situation"]], a["score"] if a["score"] is not None else 101))[:audits_n]
        s.append(P(f"Se detallan las {audits_n} auditorías con situación más desfavorable de {len(body['audits'])}; el resto se resume en el alcance "
                   "y en la situación por unidad.", small))
    for a in detail:
        br = a["by_risk"]
        block = [Paragraph(f"<b>{escape(a['code'])}</b> · {escape(a['unit'])} · fase de {escape(PHASE_LABEL.get(a['phase'], a['phase']).lower())} · "
                            f"calificación {_pct(a['score'])} ({escape(_rating(a['rating']))}) · situación {SITUATION_LABEL[a['situation']].lower()} · "
                            f"hallazgos: {br['ALTO']} alto, {br['MEDIO']} medio, {br['BAJO']} bajo"
                            + (f" · {a['limitations']} limitación(es)" if a["limitations"] else ""), text)]
        obs = a["observations"][:obs_n]
        for o in obs:
            line = f"<b>[{RISK_LABEL.get(o['risk'], o['risk'] or '—')}]</b> {escape(_cut(o['title'], 220))}"
            if cond_n and o.get("condition"):
                line += f" — {escape(_cut(o['condition'], cond_n))}"
            block.append(Paragraph("• " + line, cell))
        if len(a["observations"]) > len(obs):
            block.append(P(f"… y {len(a['observations']) - len(obs)} hallazgo(s) más en SICAS.", small))
        block.append(Spacer(1, 4))
        s.append(KeepTogether(block) if level < 3 else block[0])
        if level >= 3:
            s += block[1:]

    s.append(Paragraph("4.3 Hallazgos por tema normativo (SUDEASEG)", h2))
    if body["topics"]:
        s.append(P("El motor de reglas clasifica cada hallazgo en un tema del catálogo normativo (editable por Contraloría) y cita el "
                   "criterio de la Superintendencia de la Actividad Aseguradora y la normativa interna aplicable.", small))
        for t in body["topics"]:
            br = t["by_risk"]
            block = [Paragraph(f"<b>{escape(t['label'].capitalize())}</b> — {t['total']} hallazgo(s): {br['ALTO']} alto, {br['MEDIO']} medio, "
                               f"{br['BAJO']} bajo · unidades: {escape(', '.join(t['units']))}", text),
                     Paragraph("<b>Criterio:</b> " + escape(_cut(t["criteria"], crit_n)), cell)]
            if level < 2:
                block.append(Paragraph("<b>Efecto:</b> " + escape(_cut(t["effect"], crit_n)), cell))
                block += [P("• " + e) for e in t["examples"][: 3 if level == 0 else 2]]
            block.append(Spacer(1, 4))
            s.append(KeepTogether(block))
    else:
        s.append(P("No hay hallazgos vigentes en las auditorías seleccionadas.", text))

    # 5. Conclusión
    s.append(Paragraph("5. Conclusión", h1))
    s += [P(c, text) for c in body["conclusion"]]
    if body["recommendations"]:
        s += [Spacer(1, 3), Paragraph("<b>Recomendaciones prioritarias</b>", text)]
        s += [P("• " + _cut(r, 500 if level < 3 else 260), text) for r in body["recommendations"]]

    # 6. Firmas
    s.append(KeepTogether(_signatures(state, W, text, small, cell, hdr, h1, table, P)))
    doc.build(s, onFirstPage=furniture, onLaterPages=furniture)
    return buf.getvalue(), doc.page


def _image(data, w, h):
    try:
        img = Image(io.BytesIO(data), width=w, height=h, kind="proportional")
        img.hAlign = "LEFT"
        return img
    except Exception:  # noqa: BLE001 - imagen dañada: se deja el espacio con el nombre
        return Spacer(w, h)


def _signatures(state, W, text, small, cell, hdr, h1, table, P):
    """Auditor: iniciales de nombre y apellido. Jefe, Gerencia y Contralor: firma escaneada estampada al aprobar."""
    out = [Paragraph("6. Firmas", h1)]
    aud, jefe = state.get("auditor"), state.get("jefe")
    big = ParagraphStyle("ini", parent=cell, fontName="Helvetica-Bold", fontSize=20, leading=24)

    def box(person, label, pending, initials=False):
        if not person:
            return [Spacer(1, 1.5 * cm), P("_____________________________"), P(label, small), P(pending, small)]
        mark = (Paragraph(escape(person["initials"]), big) if initials
                else _image(person["image"], 4.6 * cm, 1.5 * cm) if person.get("image") else Spacer(1, 1.5 * cm))
        return [mark, P("_____________________________"), Paragraph(f"<b>{escape(person['name'])}</b>", cell), P(label, small),
                P(person.get("note") or f"Firmado el {person.get('date', '—')}", small)]

    def grid(cells):
        t = Table([cells], colWidths=[W / len(cells)] * len(cells))
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
        return t

    out.append(grid([box(aud, "Auditor (iniciales)", "", initials=True),
                     box(jefe, "Jefe de Auditoría", "Pendiente de la aprobación del Jefe de Auditoría")]))
    acks = {a["role"]: a for a in state.get("acks") or []}
    out += [Spacer(1, 10), Paragraph("<b>Recepción y conformidad</b>", text)]
    out.append(grid([box({**acks[r], "note": f"Recibido el {acks[r]['date']}"} if r in acks else None, r, f"Pendiente de {r}")
                     for r in ("Gerencia", "Contralor")]))
    if state.get("body_sha256"):
        out.append(P(f"Huella SHA-256 del contenido: {state['body_sha256']}", small))
    return out
