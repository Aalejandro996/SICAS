"""Genera el PDF del dictamen/providencia (ReportLab). Determinista: mismo contenido -> mismo texto."""
from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

SIGNATURE_BOX = (2 * cm, 2.2 * cm, 11 * cm, 4.6 * cm)   # x1, y1, x2, y2 (página final)


def build_dictamen_pdf(report: dict) -> bytes:
    """
    report = {"folio", "kind", "title", "company", "date", "author", "findings": [...],
              "conclusion": str, "body_sha256": str}
    Deja libre la zona inferior de la última página para el campo de firma visible.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=5.5 * cm,
                            title=report["title"], author=report.get("author", ""), subject=report["kind"])
    ss = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=ss["BodyText"], fontSize=8, textColor=colors.grey)
    el = [Paragraph(escape(report["company"]), ss["Heading3"]),
          Paragraph(f"{escape(report['kind'])} N° {escape(report['folio'])}", ss["Title"]),
          Paragraph(escape(report["title"]), ss["Heading2"]),
          Paragraph(f"Fecha: {escape(report['date'])} · Elaborado por: {escape(report.get('author', ''))}", ss["BodyText"]),
          Spacer(1, 12)]
    if report.get("findings"):
        rows = [["Regla", "Severidad", "Entidad", "Descripción"]] + [
            [f["rule_code"], f["severity"], f["entity_id"], Paragraph(escape(f["message"]), ss["BodyText"])]
            for f in report["findings"]]
        t = Table(rows, colWidths=[3 * cm, 2.2 * cm, 3.3 * cm, 8.5 * cm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3864")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        el += [Paragraph("Hallazgos", ss["Heading3"]), t, Spacer(1, 12)]
    el += [Paragraph("Conclusión", ss["Heading3"]), Paragraph(escape(report["conclusion"]), ss["BodyText"]),
           Spacer(1, 18),
           Paragraph(f"Huella SHA-256 del contenido aprobado: {report['body_sha256']}", small)]

    def footer(canvas, d):
        canvas.saveState(); canvas.setFont("Helvetica", 7); canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm, f"{report['kind']} {report['folio']} · Documento con firma electrónica; "
                                             "verifique la firma en el lector de PDF.")
        canvas.drawRightString(LETTER[0] - 2 * cm, 1.2 * cm, f"Pág. {d.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
