"""Reglas de los motores editables con doble control (lógica pura).

Motores:
  SUDEASEG  -> engagement.regulatory_catalog   (hallazgos de auditorías no de Sistemas)
  SISTEMAS  -> engagement.systems_rule_catalog (observaciones de Auditoría de Sistemas)
  ANALITICO -> engine.rule_parameters          (parámetros del motor analítico; las reglas son código)
  UNIDAD    -> engagement.units                (unidades y sucursales auditables; clave = código)
  CODIFICACION -> engagement.codification_catalog (codificación institucional; clave = CATÁLOGO:CÓDIGO)

El Administrador del Sistema propone (rule:propose) una regla nueva o un cambio con su motivo; el
Contralor (rule:configure) lo aprueba o rechaza. Quien propone no aprueba. Al aprobar se vuelve a
validar y se comprueba que la regla no cambió desde la propuesta, para no pisar cambios intermedios.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

ENGINES = ("SUDEASEG", "SISTEMAS", "ANALITICO", "UNIDAD", "CODIFICACION")
UNIT_KEY_RX = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,19}$")
CODE_CATALOGS = ("AUDIT_TYPE", "COMPANY", "PLAN_TYPE", "PROCESS", "FREQUENCY", "REPORT_COMPANY")
CODE_KEY_RX = re.compile(r"^(" + "|".join(CODE_CATALOGS) + r"):[A-Z]{1,6}$")
KEY_RX = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
GENERAL_KEY = {"SUDEASEG": "general", "SISTEMAS": "general"}
REASON_MIN = 10
MAX_PAYLOAD = 20_000

TEXT_FIELDS = {
    "SUDEASEG": ("criteria", "cause", "effect", "recommendation"),
    "SISTEMAS": ("criteria", "cause", "effect", "recommendation", "field_test"),
}
CATALOG_FIELDS = {
    "SUDEASEG": ("label", "keywords", "criteria", "cause", "effect", "recommendation", "sort_order", "active"),
    "SISTEMAS": ("label", "keywords", "criteria", "cause", "effect", "recommendation", "field_test",
                 "critical", "sort_order", "active"),
    "ANALITICO": ("params", "enabled"),
    "UNIDAD": ("name", "kind", "audit_domain", "active", "responsible_name", "responsible_role"),
    "CODIFICACION": ("label", "sort_order", "active"),
}


class RuleAdminError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass
class ChangeRequest:
    id: str
    engine: str
    rule_key: str
    payload: dict
    previous: dict | None
    reason: str
    requested_by: str
    status: str = "PENDING"


class RulesRepo(Protocol):
    def current(self, engine: str, key: str) -> dict | None: ...
    def pending_exists(self, engine: str, key: str) -> bool: ...
    def create_request(self, req: ChangeRequest) -> None: ...
    def get_request(self, request_id: str) -> ChangeRequest | None: ...
    def apply(self, engine: str, key: str, values: dict, actor: str, is_new: bool) -> None: ...
    def decide(self, request_id: str, status: str, decided_by: str, note: str) -> None: ...


def _text(v, name, lo, hi) -> str:
    v = re.sub(r"[ \t]+", " ", str(v if v is not None else "")).strip()
    if not lo <= len(v) <= hi:
        raise RuleAdminError("INVALID_DATA", f"{name}: entre {lo} y {hi} caracteres")
    return v


def _keywords(v) -> list[str]:
    if not isinstance(v, list):
        raise RuleAdminError("INVALID_DATA", "keywords: lista de palabras clave")
    kws = []
    for k in v:
        k = str(k).strip().lower()
        if k and k not in kws:
            if len(k) > 60:
                raise RuleAdminError("INVALID_DATA", "Cada palabra clave: máximo 60 caracteres")
            kws.append(k)
    if len(kws) > 60:
        raise RuleAdminError("INVALID_DATA", "Máximo 60 palabras clave")
    return kws


def _bool(v, name) -> bool:
    if not isinstance(v, bool):
        raise RuleAdminError("INVALID_DATA", f"{name}: verdadero o falso")
    return v


def _json_kind(v) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    return type(v).__name__


def validate_catalog(engine: str, key: str, values: dict) -> dict:
    """Normaliza y valida la regla completa (catálogo SUDEASEG o de Sistemas)."""
    out: dict[str, Any] = {"label": _text(values.get("label"), "label", 3, 120),
                           "keywords": _keywords(values.get("keywords") or [])}
    for f in TEXT_FIELDS[engine]:
        out[f] = _text(values.get(f), f, 10, 3000)
    try:
        out["sort_order"] = int(values.get("sort_order", 100))
    except (TypeError, ValueError):
        raise RuleAdminError("INVALID_DATA", "sort_order: número entero")
    if not 0 <= out["sort_order"] <= 999:
        raise RuleAdminError("INVALID_DATA", "sort_order: entre 0 y 999")
    out["active"] = _bool(values.get("active", True), "active")
    if engine == "SISTEMAS":
        out["critical"] = _bool(values.get("critical", False), "critical")
    if key == GENERAL_KEY[engine] and not out["active"]:
        raise RuleAdminError("INVALID_DATA", "La regla «general» es la de respaldo del motor y no puede desactivarse")
    if key != GENERAL_KEY[engine] and not out["keywords"] and out["active"]:
        raise RuleAdminError("INVALID_DATA", "Una regla activa necesita al menos una palabra clave para aplicarse")
    return out


def validate_analytic(defaults: dict, values: dict) -> dict:
    params = values.get("params", {})
    if not isinstance(params, dict):
        raise RuleAdminError("INVALID_DATA", "params: objeto JSON")
    unknown = set(params) - set(defaults)
    if unknown:
        raise RuleAdminError("INVALID_DATA", f"Parámetros desconocidos: {sorted(unknown)}")
    for k, v in params.items():
        if _json_kind(v) != _json_kind(defaults[k]):
            raise RuleAdminError("INVALID_DATA", f"{k}: debe ser del mismo tipo que el valor por defecto ({_json_kind(defaults[k])})")
    return {"params": params, "enabled": _bool(values.get("enabled", True), "enabled")}


def validate_unit(values: dict) -> dict:
    out = {"name": _text(values.get("name"), "name", 3, 120)}
    kind = str(values.get("kind") or "").upper()
    if kind not in ("SUCURSAL", "UNIDAD"):
        raise RuleAdminError("INVALID_DATA", "kind: SUCURSAL o UNIDAD")
    domain = str(values.get("audit_domain") or "GENERAL").upper()
    if domain not in ("GENERAL", "FINANCIERA", "SISTEMAS"):
        raise RuleAdminError("INVALID_DATA", "audit_domain: GENERAL, FINANCIERA o SISTEMAS")
    out.update(kind=kind, audit_domain=domain, active=_bool(values.get("active", True), "active"))
    for f in ("responsible_name", "responsible_role"):
        v = str(values.get(f) or "").strip()
        if len(v) > 200:
            raise RuleAdminError("INVALID_DATA", f"{f}: máximo 200 caracteres")
        out[f] = v or None
    return out


def validate_code(values: dict) -> dict:
    out = {"label": _text(values.get("label"), "label", 2, 150), "active": _bool(values.get("active", True), "active")}
    try:
        out["sort_order"] = int(values.get("sort_order", 100))
    except (TypeError, ValueError):
        raise RuleAdminError("INVALID_DATA", "sort_order: número entero")
    return out


def _comparable(engine: str, row: dict | None) -> dict | None:
    if row is None:
        return None
    return {f: row.get(f) for f in CATALOG_FIELDS[engine]}


class RulesAdminService:
    def __init__(self, repo: RulesRepo, audit: Callable[..., None], new_id: Callable[[], str],
                 analytic_defaults: Callable[[str], dict | None]):
        self.repo, self.audit, self.new_id, self.analytic_defaults = repo, audit, new_id, analytic_defaults

    def _resolve(self, engine: str, key: str, payload: dict) -> tuple[dict, dict | None]:
        """(valores completos validados, valores actuales o None si es una regla nueva)."""
        if engine not in ENGINES:
            raise RuleAdminError("INVALID_DATA", "Motor inválido: SUDEASEG, SISTEMAS o ANALITICO")
        if not isinstance(payload, dict) or not payload:
            raise RuleAdminError("INVALID_DATA", "Indique el contenido de la regla")
        if len(json.dumps(payload, default=str)) > MAX_PAYLOAD:
            raise RuleAdminError("INVALID_DATA", "La regla es demasiado extensa")
        extra = set(payload) - set(CATALOG_FIELDS[engine])
        if extra:
            raise RuleAdminError("INVALID_DATA", f"Campos no admitidos: {sorted(extra)}")
        current = _comparable(engine, self.repo.current(engine, key))
        if engine == "ANALITICO":
            defaults = self.analytic_defaults(key)
            if defaults is None:
                raise RuleAdminError("NOT_FOUND", "Regla analítica inexistente: las reglas nuevas del motor analítico requieren desarrollo")
            base = current or {"params": {}, "enabled": True}
            return validate_analytic(defaults, {**base, **payload}), current
        if engine == "UNIDAD":
            if not UNIT_KEY_RX.match(key or ""):
                raise RuleAdminError("INVALID_DATA", "Código de la unidad: 2 a 20 caracteres (mayúsculas, números y guiones)")
            return validate_unit({**(current or {}), **payload}), current
        if engine == "CODIFICACION":
            if not CODE_KEY_RX.match(key or ""):
                raise RuleAdminError("INVALID_DATA", "Clave: CATÁLOGO:CÓDIGO, p. ej. COMPANY:SC (código de 1 a 6 letras mayúsculas)")
            return validate_code({**(current or {}), **payload}), current
        if not KEY_RX.match(key or ""):
            raise RuleAdminError("INVALID_DATA", "Clave de la regla: 2 a 30 caracteres (minúsculas, números y _), comenzando por letra")
        return validate_catalog(engine, key, {**(current or {}), **payload}), current

    def propose(self, actor_id: str, engine: str, key: str, payload: dict, reason: str) -> str:
        engine = str(engine or "").upper()
        reason = str(reason or "").strip()
        if len(reason) < REASON_MIN:
            raise RuleAdminError("REASON_REQUIRED", f"Indique el motivo del cambio (mínimo {REASON_MIN} caracteres)")
        values, current = self._resolve(engine, key, payload)
        if current is not None and values == current:
            raise RuleAdminError("NO_CHANGE", "La propuesta no cambia la regla vigente")
        if self.repo.pending_exists(engine, key):
            raise RuleAdminError("PENDING_EXISTS", "Ya hay un cambio pendiente para esa regla")
        rid = self.new_id()
        self.repo.create_request(ChangeRequest(rid, engine, key, values, current, reason, actor_id))
        self.audit("RULE_CHANGE_REQUESTED", entity_type="rule", entity_id=f"{engine}:{key}",
                   before_data=current, after_data={"request": rid, "values": values, "reason": reason})
        return rid

    def decide(self, actor_id: str, actor_perms: set[str], request_id: str, approve: bool, note: str = "") -> str:
        if "rule:configure" not in actor_perms:
            raise RuleAdminError("FORBIDDEN", "Sin permiso para aprobar cambios de reglas")
        req = self.repo.get_request(request_id)
        if req is None or req.status != "PENDING":
            raise RuleAdminError("NOT_PENDING", "Solicitud inexistente o ya resuelta")
        if actor_id == req.requested_by:
            self.audit("RULE_DECISION_REJECTED", outcome="DENIED", entity_type="rule_change_request",
                       entity_id=request_id, metadata={"reason": "DOBLE_CONTROL"})
            raise RuleAdminError("DUAL_CONTROL", "Doble control: quien propone el cambio no puede aprobarlo")
        if approve:
            values, current = self._resolve(req.engine, req.rule_key, req.payload)   # revalida con el estado ACTUAL
            if json.dumps(current, sort_keys=True, default=str) != json.dumps(req.previous, sort_keys=True, default=str):
                raise RuleAdminError("STALE", "La regla cambió después de la propuesta; recházela y proponga de nuevo")
            self.repo.apply(req.engine, req.rule_key, values, actor_id, is_new=current is None)
        status = "APPROVED" if approve else "REJECTED"
        self.repo.decide(request_id, status, actor_id, note)
        self.audit("RULE_CHANGE_APPROVED" if approve else "RULE_CHANGE_REJECTED", entity_type="rule",
                   entity_id=f"{req.engine}:{req.rule_key}", before_data=req.previous,
                   after_data={"request": request_id, "values": req.payload if approve else None, "note": note or None})
        return status
