"""Codificación institucional de expedientes, auditorías, cartas e informes.

Fuente: docs/CODIFICACIÓN DE INFORMES.docx.

- Expediente / notificación / carta de requerimientos:
      TIPO DE AUDITORÍA - COMPAÑÍA - CORRELATIVO - AÑO FISCAL        p. ej. S-SC-001-2026
  La auditoría hereda el código de su expediente con un sufijo:       S-SC-001-2026-A1
- Informes (previo y final):
      SIGLAS - PROCESO - TIPO - COMPAÑÍA - CORRELATIVO - AÑO FISCAL   p. ej. P-S-G-SC-001-2026
El correlativo es de tres dígitos y se reinicia en cada año fiscal y combinación de prefijo.
"""
from __future__ import annotations

AUDIT_TYPES = {
    "P": "Personas",
    "A": "Auditoría de Sucursal",
    "C": "Contraloría",
    "S": "Sistema",
    "LC": "Legitimación de Capitales",
}

COMPANIES = {
    "SC": "Seguros Constitución, C.A.",
    "ASN": "Asistanet, C.A.",
    "CAR": "Caravana de la Salud, C.A.",
    "BTM": "Farmacias Botimarket, C.A.",
    "RPF": "RPF, C.A.",
    "INSG": "Financiadora de Primas Inversora Segucons, C.A.",
    "SGRK": "Segurisk Corretaje de Seguros, C.A.",
    "VIDP": "Vida y Patrimonio Corretaje de Seguros, C.A.",
    "AGC": "Águila Corretaje de Seguros, C.A.",
    "VEN": "Veneasesores Corretaje de Seguros, C.A.",
}

PLAN_TYPES = {"P": "Planificada", "E": "Especial"}

PROCESSES = {
    "O": "Operativo",
    "T": "Técnico",
    "A": "Administrativo",
    "C": "Comercial",
    "S": "Sistema",
    "E": "Especial",
    "F": "Financiera",
    "LC": "Legitimación de Capitales",
    "IS": "Inversora Segucons",
    "CR": "Compañías Relacionadas",
}

FREQUENCIES = {
    "S": "Seguimiento",
    "G": "General",
    "E": "Especial",
}

REPORT_COMPANIES = {"SC": "Seguros Constitución, C.A.", "CR": "Compañías del Grupo"}


class CodeError(ValueError):
    pass


# Los catálogos vigentes están en engagement.codification_catalog (editables con doble control);
# los diccionarios anteriores quedan como respaldo si la tabla no existe o está vacía.
_BUILTIN = {"AUDIT_TYPE": AUDIT_TYPES, "COMPANY": COMPANIES, "PLAN_TYPE": PLAN_TYPES, "PROCESS": PROCESSES,
            "FREQUENCY": FREQUENCIES, "REPORT_COMPANY": REPORT_COMPANIES}
_CACHE: dict = {"at": 0.0, "value": None}


def invalidate() -> None:
    _CACHE.update(at=0.0, value=None)


def _catalog(name: str) -> dict:
    import time
    if _CACHE["value"] is None or time.monotonic() - _CACHE["at"] > 30:
        loaded = {}
        try:
            from sqlalchemy import text

            from app.extensions import db
            for r in db.session.execute(text("SELECT catalog, code, label FROM engagement.codification_catalog "
                                             "WHERE active ORDER BY catalog, sort_order, code")):
                loaded.setdefault(r.catalog, {})[r.code] = r.label
        except Exception:  # noqa: BLE001 - sin base o sin tabla: catálogos incorporados
            try:
                from app.extensions import db
                db.session.rollback()
            except Exception:  # noqa: BLE001
                pass
            loaded = {}
        _CACHE.update(at=time.monotonic(), value=loaded)
    return _CACHE["value"].get(name) or _BUILTIN[name]


def _pick(value, catalog: dict, name: str, default: str | None = None) -> str:
    v = str(value or default or "").strip().upper()
    if v not in catalog:
        raise CodeError(f"{name}: valor inválido ({', '.join(catalog)})")
    return v


def defaults_for_domain(domain: str, unit_kind: str | None = None) -> dict:
    """Valores por defecto según el tipo de auditoría de SICAS (el usuario puede cambiarlos)."""
    domain = str(domain or "GENERAL").upper()
    if domain == "SISTEMAS":
        return {"audit_type": "S", "process": "S"}
    if domain == "FINANCIERA":
        return {"audit_type": "A" if str(unit_kind or "").upper() == "SUCURSAL" else "C", "process": "F"}
    return {"audit_type": "A" if str(unit_kind or "").upper() == "SUCURSAL" else "C", "process": "O"}


def file_fields(d: dict, domain: str, unit_kind: str | None = None) -> dict:
    base = defaults_for_domain(domain, unit_kind)
    audit_type = _pick(d.get("audit_type"), _catalog("AUDIT_TYPE"), "Tipo de auditoría", base["audit_type"])
    if str(domain).upper() == "SISTEMAS" and audit_type != "S":
        raise CodeError("Las auditorías de Sistemas usan el tipo S (Sistema)")
    return {"audit_type": audit_type, "company": _pick(d.get("company"), _catalog("COMPANY"), "Compañía", "SC")}


# Proceso, siglas y tipo por defecto según el tipo de auditoría.
KIND_DEFAULTS = {
    "OPERATIVA": {"process": "O"},
    "ESPECIAL": {"process": "E", "plan_type": "E", "frequency": "E"},
    "ADMINISTRATIVA": {"process": "A"},
    "FINANCIERA": {"process": "F"},
}


def report_fields(d: dict, domain: str, audit_kind: str | None = None) -> dict:
    base = {**defaults_for_domain(domain), **KIND_DEFAULTS.get(str(audit_kind or "").upper(), {})}
    return {
        "plan_type": _pick(d.get("plan_type"), _catalog("PLAN_TYPE"), "Siglas (planificada/especial)", base.get("plan_type", "P")),
        "process": _pick(d.get("process"), _catalog("PROCESS"), "Proceso", base["process"]),
        "frequency": _pick(d.get("frequency"), _catalog("FREQUENCY"), "Tipo (frecuencia)", base.get("frequency", "G")),
        "report_company": _pick(d.get("report_company"), _catalog("REPORT_COMPANY"), "Compañía del informe", "SC"),
    }


def file_prefix(audit_type: str, company: str) -> str:
    return f"{audit_type}-{company}"


def file_code(audit_type: str, company: str, n: int, year: int) -> str:
    return f"{file_prefix(audit_type, company)}-{n:03d}-{year}"


def audit_code(file_code_: str, n: int) -> str:
    return f"{file_code_}-A{n}"


def report_prefix(plan_type: str, process: str, frequency: str, company: str) -> str:
    return f"{plan_type}-{process}-{frequency}-{company}"


def report_code(prefix: str, n: int, year: int) -> str:
    return f"{prefix}-{n:03d}-{year}"


def catalogs() -> dict:
    """Catálogos para los formularios."""
    return {"audit_types": _catalog("AUDIT_TYPE"), "companies": _catalog("COMPANY"), "plan_types": _catalog("PLAN_TYPE"),
            "processes": _catalog("PROCESS"), "frequencies": _catalog("FREQUENCY"), "report_companies": _catalog("REPORT_COMPANY")}
