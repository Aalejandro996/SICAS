"""Máquina de estados y reglas de doble control de informes. Lógica pura (sin Flask/BD): fácil de auditar y probar."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

DRAFT, SUBMITTED, RETURNED, APPROVED, SIGNED = "DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "SIGNED"

TRANSITIONS = {
    DRAFT: {SUBMITTED},
    RETURNED: {SUBMITTED},
    SUBMITTED: {APPROVED, RETURNED},
    APPROVED: {SIGNED},
    SIGNED: set(),          # estado final: cualquier cambio exige un nuevo informe/versión
}


class WorkflowError(Exception):
    pass


@dataclass
class ReportState:
    id: str
    status: str
    drafted_by: str
    approved_by: str | None
    body: dict
    approved_body_sha256: str | None = None


def body_hash(body: dict) -> str:
    """Hash canónico del contenido (claves ordenadas, sin espacios): base de la integridad aprobado -> firmado."""
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _move(r: ReportState, to: str) -> None:
    if to not in TRANSITIONS[r.status]:
        raise WorkflowError(f"Transición no permitida: {r.status} -> {to}")


def can_submit(r: ReportState, actor: str) -> None:
    _move(r, SUBMITTED)
    if actor != r.drafted_by:
        raise WorkflowError("Solo el redactor puede enviar el borrador a aprobación.")


def can_approve(r: ReportState, actor: str) -> None:
    _move(r, APPROVED)
    if actor == r.drafted_by:
        raise WorkflowError("Doble control: el aprobador no puede ser el redactor.")


def can_sign(r: ReportState, actor: str) -> None:
    _move(r, SIGNED)
    if actor == r.drafted_by:
        raise WorkflowError("Doble control: el firmante no puede ser el redactor.")
    if r.approved_body_sha256 != body_hash(r.body):
        raise WorkflowError("El contenido cambió después de la aprobación; requiere nueva aprobación.")
