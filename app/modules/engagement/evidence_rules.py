"""Validación de archivos de evidencia (lógica pura)."""
from __future__ import annotations

import os
import re

MAX_BYTES = 25 * 1024 * 1024
ALLOWED = {  # extensión -> (content-type que SICAS asigna, firma esperada al inicio del archivo o None)
    ".pdf": ("application/pdf", b"%PDF"), ".png": ("image/png", b"\x89PNG"), ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"), ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", b"PK"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK"),
    ".csv": ("text/csv", None), ".txt": ("text/plain", None), ".eml": ("message/rfc822", None),
}


class EvidenceError(ValueError):
    pass


def safe_filename(name: str) -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    base = re.sub(r"[\x00-\x1f<>:\"|?*]", "", base).strip(". ")
    if not base:
        raise EvidenceError("Nombre de archivo inválido")
    stem, ext = os.path.splitext(base)
    return stem[:100] + ext.lower()


def check(filename: str, data: bytes) -> tuple[str, str]:
    """Devuelve (nombre_seguro, content_type). El tipo lo decide el servidor por extensión y firma, no el navegador."""
    name = safe_filename(filename)
    ext = os.path.splitext(name)[1]
    if ext not in ALLOWED:
        raise EvidenceError("Tipo de archivo no permitido (use " + ", ".join(sorted(ALLOWED)) + ")")
    if not data:
        raise EvidenceError("El archivo está vacío")
    if len(data) > MAX_BYTES:
        raise EvidenceError("El archivo supera 25 MB")
    ctype, magic = ALLOWED[ext]
    if magic and not data.startswith(magic):
        raise EvidenceError("El contenido no corresponde a la extensión del archivo")
    return name, ctype
