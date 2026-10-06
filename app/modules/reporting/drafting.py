"""Redacción de informes (lógica pura): validación, folio y armado del cuerpo que luego se aprueba y se firma."""
from __future__ import annotations

from datetime import date

KINDS = {"DICTAMEN": "DICT", "PROVIDENCIA": "PROV", "REGULATORIO": "REG"}


class DraftError(ValueError):
    pass


def make_folio(kind: str, year: int, n: int) -> str:
    return f"{KINDS[kind]}-{year}-{n:06d}"


def validate_draft(kind, title, conclusion, finding_ids) -> tuple[str, str, str, list[int]]:
    if kind not in KINDS:
        raise DraftError("Tipo de informe inválido")
    title, conclusion = (title or "").strip(), (conclusion or "").strip()
    if not 5 <= len(title) <= 200:
        raise DraftError("El título debe tener entre 5 y 200 caracteres")
    if not 20 <= len(conclusion) <= 5000:
        raise DraftError("La conclusión debe tener entre 20 y 5000 caracteres")
    if not isinstance(finding_ids, list) or len(finding_ids) > 100 or not all(isinstance(i, int) and not isinstance(i, bool) for i in finding_ids):
        raise DraftError("Hallazgos inválidos (máximo 100)")
    return kind, title, conclusion, sorted(set(finding_ids))


def build_body(*, folio: str, kind: str, title: str, company: str, author: str, on: date,
               findings: list[dict], conclusion: str) -> dict:
    """Cuerpo canónico del informe. Es lo que se hashea al aprobar; no debe contener datos personales de asegurados."""
    return {
        "folio": folio, "kind": kind, "title": title, "company": company, "author": author, "date": on.isoformat(),
        "findings": [{"id": f["id"], "rule_code": f["rule_code"], "severity": f["severity"],
                      "entity_id": str(f["entity_id"]), "message": f["message"]} for f in findings],
        "conclusion": conclusion,
    }
