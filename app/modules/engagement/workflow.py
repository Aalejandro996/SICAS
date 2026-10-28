"""Flujo de autorización del informe final.

FINAL:
  DRAFT/RETURNED -> IN_REVIEW (Jefe)
  Jefe: devolver | aprobar -> GERENCIA
  Gerente: devolver | aprobar+firmar -> CONTRALOR
  Contralor: devolver | aprobar+firmar -> SIGNED
  Sin Gerente en el cargo (ningún usuario activo con el rol ni suplente): el Jefe aprueba -> CONTRALOR y la etapa
  de Gerencia queda omitida (gerencia_omitted); el Contralor firma sin la firma previa de Gerencia.

Las aprobaciones de Jefe, Gerente y Contralor quedan atadas al SHA-256 del contenido.
Las firmas PAdES de Gerente y Contralor también quedan atadas al contenido firmado.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class WorkflowError(Exception):
    pass


@dataclass
class ReportState:
    kind: str
    status: str
    created_by: str
    body_sha256: str
    team_ids: list[str] = field(default_factory=list)
    initialed_ids: set[str] = field(default_factory=set)
    jefe_approved_by: str | None = None
    jefe_approved_body_sha256: str | None = None
    gerente_approved_by: str | None = None
    gerente_approved_body_sha256: str | None = None
    contralor_approved_by: str | None = None
    contralor_approved_body_sha256: str | None = None
    approved_by: str | None = None
    approved_body_sha256: str | None = None
    signed_roles: dict[str, str] = field(default_factory=dict)
    gerencia_omitted: bool = False
    signed_hashes: dict[str, str] = field(default_factory=dict)


def _need(cond: bool, msg: str):
    if not cond:
        raise WorkflowError(msg)


def can_edit(s: ReportState, actor: str | None = None) -> None:
    _need(s.status in ("DRAFT", "RETURNED"), "El informe ya no es editable")


def can_initial(s: ReportState, actor: str) -> None:
    _need(s.kind == "FINAL", "Las iniciales se estampan en el informe final")
    _need(s.status in ("DRAFT", "RETURNED"), "Solo se estampan iniciales antes de enviar a revisión")
    _need(actor in s.team_ids, "Solo los auditores del equipo estampan sus iniciales")


def can_submit_final(s: ReportState, actor: str) -> None:
    _need(s.kind == "FINAL", "No es un informe final")
    _need(s.status in ("DRAFT", "RETURNED"), f"No se puede enviar un informe en estado {s.status}")
    _need(actor in s.team_ids, "Solo el equipo auditor envía el informe al Jefe de Auditoría")
    missing = [t for t in s.team_ids if t not in s.initialed_ids]
    _need(not missing, f"Faltan las iniciales de {len(missing)} auditor(es) del equipo")


def can_send_previo(s: ReportState, actor: str) -> None:
    _need(s.kind == "PREVIO" and s.status == "DRAFT", "Solo un informe previo en borrador se envía a la unidad")
    _need(actor in s.team_ids, "Solo el equipo auditor envía el informe previo")


def can_jefe_review(s: ReportState, actor: str) -> None:
    _need(s.kind == "FINAL" and s.status == "IN_REVIEW", "El informe no está pendiente del Jefe de Auditoría")
    _need(actor != s.created_by and actor not in s.team_ids, "El Jefe no puede pertenecer al equipo auditor ni ser quien generó el informe")
    _need(s.jefe_approved_body_sha256 in (None, s.body_sha256), "La aprobación del Jefe no corresponde al contenido actual")


def can_gerente_review(s: ReportState, actor: str) -> None:
    _need(s.kind == "FINAL" and s.status == "GERENCIA", "El informe no está pendiente de Gerencia")
    _need(s.jefe_approved_body_sha256 == s.body_sha256, "Falta la aprobación vigente del Jefe de Auditoría")
    _need(actor != s.created_by and actor not in s.team_ids, "Gerencia no puede pertenecer al equipo auditor")
    _need(actor != s.jefe_approved_by, "El Gerente debe ser distinto del Jefe que aprobó")
    _need(s.gerente_approved_body_sha256 in (None, s.body_sha256), "La aprobación de Gerencia no corresponde al contenido actual")


def can_contralor_review(s: ReportState, actor: str) -> None:
    _need(s.kind == "FINAL" and s.status == "CONTRALOR", "El informe no está pendiente del Contralor")
    _need(s.jefe_approved_body_sha256 == s.body_sha256, "Falta la aprobación vigente del Jefe")
    _need(s.gerencia_omitted or s.gerente_approved_body_sha256 == s.body_sha256, "Falta la aprobación vigente de Gerencia")
    _need(actor != s.created_by and actor not in s.team_ids, "El Contralor no puede pertenecer al equipo auditor")
    _need(actor != s.jefe_approved_by and actor != s.gerente_approved_by, "El Contralor debe ser distinto de los revisores anteriores")
    _need(s.contralor_approved_body_sha256 in (None, s.body_sha256), "La aprobación del Contralor no corresponde al contenido actual")

def can_review(s: ReportState, actor: str) -> None:
    """Valida la revisión/aprobación según la etapa actual del informe.

    Flujo:
      IN_REVIEW -> Jefe de Auditoría
      GERENCIA  -> Gerente
      CONTRALOR -> Contralor

    La autorización por dominio/rol se controla en api.py mediante RBAC;
    aquí solo se valida el estado y las condiciones propias del workflow.
    """
    if s.status == "IN_REVIEW":
        can_jefe_review(s, actor)
        return

    if s.status == "GERENCIA":
        can_gerente_review(s, actor)
        return

    if s.status == "CONTRALOR":
        can_contralor_review(s, actor)
        return

    raise WorkflowError(
        f"El informe no está en una etapa de revisión válida: {s.status}"
    )

def can_comment(s: ReportState, actor: str) -> None:
    _need(s.kind == "FINAL" and s.status in ("IN_REVIEW", "GERENCIA", "CONTRALOR", "RETURNED"), "El informe no está en revisión")


def can_sign(s: ReportState, actor: str, role: str) -> None:
    _need(s.kind == "FINAL", "Solo se firma el informe final")
    _need(role in ("CONTRALOR", "GERENTE_CI"), "Rol de firma inválido")
    _need(actor != s.created_by and actor not in s.team_ids, "El equipo auditor no firma")
    if role == "GERENTE_CI":
        can_gerente_review(s, actor)
        _need(s.gerente_approved_by in (None, actor), "La aprobación de Gerencia corresponde al firmante")
    else:
        can_contralor_review(s, actor)
        _need(s.contralor_approved_by in (None, actor), "La aprobación del Contralor corresponde al firmante")


def is_fully_signed(s: ReportState) -> bool:
    return ({"CONTRALOR"} if s.gerencia_omitted else {"CONTRALOR", "GERENTE_CI"}) <= set(s.signed_roles)


def can_send_pac(final: ReportState | None) -> None:
    _need(final is not None and final.status == "SIGNED", "El PAC se envía cuando el informe final está aprobado y firmado")
