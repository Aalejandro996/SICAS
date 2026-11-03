"""Encuesta direccionada en Excel (una por área destinataria) para auditorías de aplicativos.

Cada área recibe solo sus preguntas, redactadas en segunda persona, con la evidencia que debe adjuntar y el dato
medible cuando aplica. Las columnas de respuesta tienen listas desplegables (Sí/No y estado de la evidencia).
La hoja oculta «_control» lleva la auditoría, el área, los códigos y un HMAC-SHA256 con una clave del servidor:
un archivo alterado, de otra auditoría o de otra área se rechaza al cargarlo.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
from datetime import date, datetime

from . import app_audit as ap

MAGIC = "SICAS-ENCUESTA-1"
MAX_BYTES = 5 * 1024 * 1024
FIRST_ROW = 10
COLS = ["N°", "Código", "Bloque", "Pregunta dirigida a su área", "Evidencia que debe adjuntar", "Dato solicitado",
        "Objetivo", "¿Cumple? (Sí / No)", "Dato informado", "¿Adjunta evidencia? (Sí / No)",
        "Estado de la evidencia", "Comentario"]
ANSWER_COLS = {"control": 8, "dato": 9, "documental": 10, "evidencia": 11, "comment": 12}


class SurveyError(ValueError):
    pass


def _sign(secret: bytes, payload: dict) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hmac.new(secret, text.encode(), hashlib.sha256).hexdigest()


def _put(ws, row, col, value):
    c = ws.cell(row=row, column=col)
    c.value = value
    if isinstance(value, str) and value[:1] in "=+-@":
        c.data_type = "s"
    return c


def build(audit: dict, app: dict, area: str, criteria: list[dict], items: list[dict], params: dict,
          secret: bytes, generated_by: str, now: datetime | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    rows = ap.survey_rows(criteria, area, items, params)
    if not rows:
        raise SurveyError("El área no tiene preguntas en esta auditoría")
    now = now or datetime.now()
    wb = Workbook()
    ws = wb.active
    ws.title = "Encuesta"
    navy, light = PatternFill("solid", fgColor="1F3864"), PatternFill("solid", fgColor="FFF9E5")
    grey = PatternFill("solid", fgColor="E7E9EF")
    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    bold, white = Font(name="Arial", bold=True, size=12), Font(name="Arial", bold=True, color="FFFFFF", size=10)
    base = Font(name="Arial", size=10)
    wrap = Alignment(wrap_text=True, vertical="top")

    _put(ws, 1, 1, f"ENCUESTA DE AUDITORÍA TI — {app.get('name', '')}").font = bold
    _put(ws, 2, 1, f"Dirigida a: {ap.AREAS.get(area, area)}").font = Font(name="Arial", bold=True, size=11, color="1F3864")
    _put(ws, 3, 1, f"Auditoría {audit['code']} · Generada el {now:%d/%m/%Y %H:%M} por {generated_by}").font = base
    _put(ws, 4, 1, "Responda cada pregunta de su área. Si responde «No», indique el motivo en el comentario. Si la pregunta "
                   "pide un dato, infórmelo: Auditoría lo contrasta con el objetivo del aplicativo. Adjunte la evidencia "
                   "indicada al devolver esta encuesta. No modifique las columnas grises ni la hoja oculta.").alignment = wrap
    ws.merge_cells("A4:L4")
    ws.row_dimensions[4].height = 42
    for r, (label, key) in enumerate((("Nombre de quien responde", "name"), ("Cargo", "role"), ("Fecha de respuesta (dd/mm/aaaa)", "date")), start=5):
        _put(ws, r, 1, label).font = Font(name="Arial", bold=True, size=10)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=3)
        c = _put(ws, r, 4, None)
        c.fill, c.border = light, box
    for col, title in enumerate(COLS, start=1):
        c = _put(ws, FIRST_ROW - 1, col, title)
        c.font, c.fill, c.alignment, c.border = white, navy, Alignment(wrap_text=True, vertical="center"), box
    widths = [5, 9, 22, 60, 38, 26, 22, 12, 14, 14, 18, 40]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    yes_no = DataValidation(type="list", formula1='"Sí,No"', allow_blank=True)
    states = DataValidation(type="list", formula1='"Actualizado,Desactualizado,Inexistente"', allow_blank=True)
    ws.add_data_validation(yes_no)
    ws.add_data_validation(states)
    show = {"SI": "Sí", "NO": "No", "ACTUALIZADO": "Actualizado", "DESACTUALIZADO": "Desactualizado", "INEXISTENTE": "Inexistente"}
    for i, r in enumerate(rows):
        row = FIRST_ROW + i
        vals = [i + 1, r["code"], r["block"], r["question"], r["evidence"], r["data_label"] or "—", r["target"] or "—",
                show.get(r["control"], None), r["dato"], show.get(r["documental"], None), show.get(r["evidencia"], None), r["comment"] or None]
        for col, v in enumerate(vals, start=1):
            c = _put(ws, row, col, v)
            c.font, c.alignment, c.border = base, wrap, box
            c.fill = light if col >= 8 else grey
        if not r["data_type"]:
            ws.cell(row=row, column=9).fill = grey
        yes_no.add(f"H{row}")
        yes_no.add(f"J{row}")
        states.add(f"K{row}")
        ws.row_dimensions[row].height = 60
    ws.freeze_panes = f"E{FIRST_ROW}"

    ctl = wb.create_sheet("_control")
    payload = {"magic": MAGIC, "audit": str(audit["id"]), "area": area, "codes": [r["code"] for r in rows]}
    ctl["A1"] = json.dumps(payload, ensure_ascii=False)
    ctl["A2"] = _sign(secret, payload)
    ctl.sheet_state = "veryHidden"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def parse(data: bytes, secret: bytes, audit_id: str, criteria: list[dict]) -> dict:
    """Respuestas de una encuesta devuelta: {area, respondent, answers: {código: resultado}}."""
    from openpyxl import load_workbook

    if not data or len(data) > MAX_BYTES or not data.startswith(b"PK"):
        raise SurveyError("Adjunte la encuesta en Excel (.xlsx) de hasta 5 MB")
    try:
        wb = load_workbook(io.BytesIO(data), data_only=True, keep_links=False)
    except Exception as exc:  # noqa: BLE001
        raise SurveyError("No fue posible leer el archivo Excel") from exc
    if "_control" not in wb.sheetnames or "Encuesta" not in wb.sheetnames:
        raise SurveyError("El archivo no es una encuesta generada por el sistema")
    try:
        payload = json.loads(wb["_control"]["A1"].value or "{}")
    except (TypeError, ValueError) as exc:
        raise SurveyError("La hoja de control de la encuesta está dañada") from exc
    sig = str(wb["_control"]["A2"].value or "")
    if payload.get("magic") != MAGIC or not hmac.compare_digest(sig, _sign(secret, payload)):
        raise SurveyError("La firma de control no coincide: el archivo fue alterado o no lo generó este sistema")
    if payload.get("audit") != str(audit_id):
        raise SurveyError("La encuesta pertenece a otra auditoría")
    ws = wb["Encuesta"]
    respondent = {"name": str(ws.cell(5, 4).value or "").strip()[:160] or None,
                  "role": str(ws.cell(6, 4).value or "").strip()[:160] or None,
                  "date": _date(ws.cell(7, 4).value)}
    by_code = {c["code"]: c for c in criteria}
    allowed = set(payload.get("codes") or [])
    answers, problems = {}, []
    for row in range(FIRST_ROW, FIRST_ROW + len(allowed) + 5):
        code = str(ws.cell(row, 2).value or "").strip()
        if not code:
            continue
        if code not in allowed or code not in by_code:
            problems.append(f"Fila {row}: el código {code} no pertenece a esta encuesta; se ignora")
            continue
        raw = {k: ws.cell(row, col).value for k, col in ANSWER_COLS.items()}
        parsed = ap.parse_survey_answer(by_code[code], raw)
        if parsed is None:
            continue
        if parsed.get("control") == "NO" and not parsed.get("comentario"):
            problems.append(f"{code}: respondió «No» sin comentario del motivo")
        if by_code[code].get("data") and raw.get("dato") not in (None, "") and "dato" not in parsed:
            problems.append(f"{code}: el dato informado no es válido ({raw.get('dato')})")
        answers[code] = parsed
    return {"area": payload["area"], "respondent": respondent, "answers": answers, "problems": problems,
            "questions": len(allowed)}
