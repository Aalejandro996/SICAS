"""Importación segura del cuestionario oficial de Auditoría de Sistemas / ERPs TI."""
from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import load_workbook

from .templates import SYSTEM_ERP_CONTROLS

MAX_BYTES = 25 * 1024 * 1024
SHEET_NAME = "ERPs TI"
SECURITY_SHEET_NAME = "Seguridad_de_TI"


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().upper().replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U").split())


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _control(value: Any) -> str:
    v = _norm(value)
    if v in {"SI", "SÍ"}:
        return "SI"
    if v in {"NO"}:
        return "NO"
    if v in {"PARCIAL", "PARCIALMENTE"}:
        return "PARCIAL"
    return ""


def _doc(value: Any) -> str:
    v = _norm(value)
    return "SI" if v in {"SI", "SÍ"} else "NO" if v == "NO" else ""


def _evidence(value: Any) -> str:
    v = _norm(value)
    if v == "ACTUALIZADO":
        return "ACTUALIZADO"
    if v == "DESACTUALIZADO":
        return "DESACTUALIZADO"
    if v == "INEXISTENTE":
        return "INEXISTENTE"
    return ""


def _parse_erp_ti(wb) -> dict:
    if SHEET_NAME not in wb.sheetnames:
        raise ValueError(f"El Excel debe contener la hoja '{SHEET_NAME}'")
    ws = wb[SHEET_NAME]
    expected = {i: (q, section) for i, q, section in SYSTEM_ERP_CONTROLS}
    found: dict[int, dict] = {}
    for row in ws.iter_rows(min_row=1, max_col=9, values_only=True):
        raw_id = row[1]
        try:
            control_id = int(raw_id) if raw_id is not None else None
        except (TypeError, ValueError):
            control_id = None
        if control_id not in expected:
            continue
        question = _text(row[2])
        expected_question = expected[control_id][0]
        if _norm(question) != _norm(expected_question):
            raise ValueError(f"El control {control_id} no coincide con la plantilla oficial")
        observation = _text(row[8])
        if observation.startswith("(Indique Nombre") or observation.startswith("(Indique la justificación"):
            observation = ""
        found[control_id] = {
            "control_id": control_id,
            "source_id": str(control_id),
            "ref": f"TI{control_id:03d}",
            "question": expected_question,
            "section": expected[control_id][1],
            "control": _control(row[3]),
            "documental": _doc(row[4]),
            "evidencia": _evidence(row[5]),
            "observation": observation[:2000] or None,
        }
    missing = sorted(set(expected) - set(found))
    if missing:
        raise ValueError("Faltan controles oficiales en el Excel: " + ", ".join(str(x) for x in missing[:20]))
    return {"questionnaire_type": "ERP_TI", "rows": [found[i] for i in sorted(found)], "controls": len(found)}


def _parse_security_ti(wb) -> dict:
    """Lee la plantilla real de Seguridad de TI sin inventar controles faltantes.

    El libro contiene 63 controles identificables con IDs como 1.1, 1.2, ... 17.3.
    Los demás controles, si la cédula ya tiene una estructura mayor, se completan
    manualmente desde SICAS; nunca se fabrican respuestas ni preguntas.
    """
    if SECURITY_SHEET_NAME not in wb.sheetnames:
        raise ValueError(f"El Excel debe contener la hoja '{SECURITY_SHEET_NAME}'")
    ws = wb[SECURITY_SHEET_NAME]
    found = []
    seen = set()
    import re
    for row in ws.iter_rows(min_row=8, max_col=8, values_only=True):
        raw_id = _text(row[1])
        if not re.fullmatch(r"\d+\.\d+", raw_id):
            continue
        if raw_id in seen:
            raise ValueError(f"El control {raw_id} está repetido en el Excel")
        seen.add(raw_id)
        question = _text(row[2])
        if not question:
            raise ValueError(f"El control {raw_id} no tiene pregunta de auditoría")
        observation = _text(row[7])
        if observation in {"Detalle:", "(Indique la justificación, evidencia o plan de acción si aplica...)"}:
            observation = ""
        # SEC + ID sin punto: 1.1 -> SEC11. Es un código interno estable;
        # el ID original se conserva en source_id para trazabilidad.
        ref = "SEC" + raw_id.replace(".", "")
        found.append({
            "control_id": raw_id,
            "source_id": raw_id,
            "ref": ref,
            "question": question,
            "section": "Seguridad de TI",
            "control": _control(row[3]),
            "documental": _doc(row[4]),
            "evidencia": _evidence(row[5]),
            "observation": observation[:2000] or None,
        })
    if not found:
        raise ValueError("No se encontraron controles en la hoja 'Seguridad_de_TI'")
    return {"questionnaire_type": "SEGURIDAD_TI", "rows": found, "controls": len(found)}


def parse(data: bytes) -> dict:
    if not data:
        raise ValueError("El archivo está vacío")
    if len(data) > MAX_BYTES:
        raise ValueError("El cuestionario supera 25 MB")
    if not data.startswith(b"PK"):
        raise ValueError("El archivo no es un XLSX válido")
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("No fue posible leer el archivo Excel") from exc

    # Se soportan las dos plantillas reales. No se exige que un cuestionario
    # de Seguridad de TI tenga la hoja ERPs TI.
    if SECURITY_SHEET_NAME in wb.sheetnames:
        return _parse_security_ti(wb)
    return _parse_erp_ti(wb)

