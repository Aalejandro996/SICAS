"""Informe PDF de la Evaluación TI de las sucursales con su marco normativo (SUDEASEG, ISO/IEC 27001:2022 y COBIT 2019)."""
from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#1F3556")
CRIT_COLOR = {"CRITICA": "#F8D4D4", "ALTA": "#FDE4C8", "MEDIA": "#FFF1C2", "BAJA": "#D7F0DF"}
CRIT_LABEL = {"CRITICA": "Crítica", "ALTA": "Alta", "MEDIA": "Media", "BAJA": "Baja"}
LEVEL_LABEL = {1: "Nivel 1: Óptimo", 2: "Nivel 2: Satisfactorio", 3: "Nivel 3: Requiere mejoras", 4: "Nivel 4: Crítico"}


def _pct(v):
    return "—" if v is None else f"{v:.1f} %"


def _date(v):
    return "—" if v is None else (v.strftime("%d/%m/%Y") if hasattr(v, "strftime") else str(v)[:10])


def build(data: dict, filters: dict, sudeaseg: str, company: str, author: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(LETTER), leftMargin=1.6 * cm, rightMargin=1.6 * cm, topMargin=1.4 * cm,
                            bottomMargin=1.4 * cm, title="Informe de Evaluación TI de sucursales", author=author)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=NAVY, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=NAVY, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#4A5A70"))
    cell = ParagraphStyle("c", parent=body, fontSize=7.8, leading=9.6)
    head = ParagraphStyle("hc", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    P = lambda t, st=cell: Paragraph(escape(str(t)) if t is not None else "—", st)

    def table(header, rows, widths, colors_by_row=None):
        t = Table([[Paragraph(h, head) for h in header], *rows], colWidths=widths, repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#C9D3E3")),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        for i, c in (colors_by_row or {}).items():
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor(c)))
        t.setStyle(TableStyle(style))
        return t

    k, rows, questions = data["kpis"], data["rows"], data["questions"]
    W = doc.width
    s = [Paragraph("Informe de Evaluación TI de las sucursales", h1),
         Paragraph(f"{escape(company)} · Contraloría · Auditoría de Sistemas · Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')} por {escape(author)}", small),
         Paragraph("Filtros: " + escape(filters.get("text") or "todas las evaluaciones"), small), Spacer(1, 6)]

    # 1. Resumen
    s.append(Paragraph("1. Resumen", h2))
    crit = k["by_criticality"]
    s.append(Paragraph(
        f"Se consolidan <b>{k['evaluations']}</b> evaluación(es) de <b>{k['branches']}</b> sucursal(es), con <b>{k['collaborators']}</b> "
        f"colaborador(es) entrevistados. Nota promedio: <b>{_pct(k['avg_score'])}</b>. Criticidad: {crit['CRITICA']} crítica(s), "
        f"{crit['ALTA']} alta(s), {crit['MEDIA']} media(s) y {crit['BAJA']} baja(s). {k['with_sod']} sucursal(es) presentan conflictos de "
        f"perfiles ({k['sod_people']} colaborador(es)).", body))
    worst = [r for r in rows if r["criticality"] in ("CRITICA", "ALTA")]
    top = [q for q in questions if (q["fail_rate"] or 0) > 0][:5]
    concl = ("La evaluación muestra debilidades relevantes en la seguridad de la información de las sucursales"
             if worst or k["with_sod"] else "La evaluación no muestra debilidades críticas en las sucursales evaluadas")
    if top:
        concl += "; los aspectos con mayor incumplimiento son " + ", ".join(f"{q['topic'].lower()} ({_pct(q['fail_rate'])})" for q in top[:3])
    s.append(Paragraph(concl + ".", body))

    # 2. Resultados por sucursal
    s.append(Paragraph("2. Resultados por sucursal", h2))
    trs, cmap = [], {}
    for i, r in enumerate(rows, 1):
        cmap[i] = CRIT_COLOR.get(r["criticality"], "#FFFFFF")
        trs.append([P(r["unit_name"]), P(r["audit_code"]), P(_date(r["closed_at"])), P(r["collaborators"]), P(_pct(r["score"])),
                    P(LEVEL_LABEL.get(r["level"], "—")), P(CRIT_LABEL.get(r["criticality"], "—")), P(r["sod_conflicts"]), P(r["dictamen"])])
    s.append(table(["Sucursal", "Auditoría", "Cierre", "Colab.", "Nota", "Nivel", "Criticidad", "Conflictos SoD", "Dictamen"],
                   trs or [[P("Sin evaluaciones para los filtros elegidos")] + [P("")] * 8],
                   [W * x for x in (0.15, 0.13, 0.08, 0.06, 0.07, 0.15, 0.08, 0.08, 0.20)], cmap))

    # 3. Resultados por aspecto evaluado con su referencia normativa
    s.append(Paragraph("3. Resultados por aspecto evaluado y criterio normativo", h2))
    s.append(Paragraph("Porcentaje de respuestas desfavorables: «No» en el Módulo I (ciberseguridad) y «Sí» en el Módulo II (perfiles y "
                       "segregación de funciones).", small))
    qrs = [[P(q["number"]), P(f"Módulo {q['module']}"), P(q["topic"]), P(_pct(q["fail_rate"])), P(q["iso"]), P(q["cobit"])]
           for q in sorted(questions, key=lambda q: int(q["number"]))]
    s.append(table(["N°", "Módulo", "Aspecto", "Incumplimiento", "ISO/IEC 27001:2022", "COBIT 2019"],
                   qrs or [[P("—")] * 6], [W * x for x in (0.04, 0.08, 0.2, 0.1, 0.33, 0.25)]))

    # 4. Recomendaciones
    s.append(Paragraph("4. Hallazgos principales y recomendaciones", h2))
    if top:
        for q in top:
            s.append(Paragraph(f"<b>{escape(q['topic'])}</b> ({_pct(q['fail_rate'])} de respuestas desfavorables). Criterio: "
                               f"{escape(q['iso'])}; {escape(q['cobit'])}; {escape(sudeaseg)}", body))
    else:
        s.append(Paragraph("No se registran respuestas desfavorables en las evaluaciones consolidadas.", body))
    if k["with_sod"]:
        s.append(Paragraph("<b>Conflictos de perfiles.</b> Revisar y depurar los perfiles de los colaboradores señalados en cada sucursal, "
                           "retirar los permisos de cargos anteriores y separar las funciones de registro y aprobación "
                           "(ISO/IEC 27001:2022 A.5.3 y A.5.18; COBIT 2019 DSS06.03).", body))

    # 5. Marco normativo y metodología
    s.append(Paragraph("5. Marco normativo y metodología", h2))
    for t in (f"<b>SUDEASEG.</b> {escape(sudeaseg)}",
              "<b>ISO/IEC 27001:2022.</b> Controles del Anexo A citados por cada aspecto (organizacionales 5.x, de personas 6.x, físicos 7.x y tecnológicos 8.x).",
              "<b>COBIT 2019.</b> Objetivos de gestión APO (alinear, planificar y organizar) y DSS (entregar, dar servicio y soporte).",
              "<b>Metodología.</b> Cada colaborador responde 15 preguntas de ciberseguridad (Módulo I) y 5 de perfiles (Módulo II). Nivel por "
              "respuestas favorables del Módulo I: 14 o más Nivel 1 (riesgo bajo), 11 a 13 Nivel 2 (medio-bajo), 8 a 10 Nivel 3 (medio-alto), "
              "menos de 8 Nivel 4 (alto). Un conflicto de perfiles limita la nota del colaborador al nivel crítico. La nota de la sucursal es el "
              "promedio de sus colaboradores y su criticidad corresponde al nivel de esa nota."):
        s.append(Paragraph(t, body))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6A768A"))
        canvas.drawString(d.leftMargin, 0.8 * cm, f"{company} · Evaluación TI de sucursales")
        canvas.drawRightString(d.pagesize[0] - d.rightMargin, 0.8 * cm, f"Pág. {d.page}")
        canvas.restoreState()

    doc.build(s, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
