"""
Fuente única de verdad del RBAC.

De este archivo se generan:
  - sql/003_rbac_seed.sql        (python scripts/generate_rbac_seed.py)
  - docs/RBAC_MATRIX.md          (mismo script)
El código de autorización usa los mismos códigos de permiso (decorador permission_required).
"""
from __future__ import annotations

# ---------------------------------------------------------------- Roles
AUDITOR = "AUDITOR"
CONTRALOR = "CONTRALOR"
SYS_ADMIN = "SYS_ADMIN"
GERENCIA = "GERENCIA"
AUDITOR_FINANCIERO = "AUDITOR_FINANCIERO"
JEFE_AUDITORIA_FINANCIERA = "JEFE_AUDITORIA_FINANCIERA"
AUDITOR_SISTEMAS = "AUDITOR_SISTEMAS"
JEFE_AUDITORIA_SISTEMAS = "JEFE_AUDITORIA_SISTEMAS"

ROLES = {
    AUDITOR: "Ejecuta cargas, reglas de análisis, gestiona hallazgos y redacta informes.",
    CONTRALOR: "Aprueba y firma dictámenes, cierra hallazgos, configura reglas y supervisa el audit trail.",
    SYS_ADMIN: "Administra plataforma, usuarios, respaldos y salud. Sin acceso a datos de negocio.",
    GERENCIA: "Consulta indicadores ejecutivos e informes aprobados y firmados (solo lectura).",
    AUDITOR_FINANCIERO: "Ejecuta auditorías financieras, sus cédulas, evidencias e informes en borrador, con alcance exclusivo financiero.",
    JEFE_AUDITORIA_FINANCIERA: "Supervisa y coordina auditorías financieras, con alcance exclusivo financiero; no aprueba ni firma como Contralor o Gerente.",
    AUDITOR_SISTEMAS: "Ejecuta auditorías de sistemas/TI, sus evidencias e informes en borrador, con alcance exclusivo de sistemas.",
    JEFE_AUDITORIA_SISTEMAS: "Supervisa y coordina auditorías de sistemas/TI, con alcance exclusivo de sistemas; no aprueba ni firma como Contralor o Gerente.",
}

# ---------------------------------------------------------- Permisos por módulo
# código -> (módulo, descripción)
PERMISSIONS: dict[str, tuple[str, str]] = {
    # Administración y sistemas
    "user:read": ("admin", "Ver usuarios"),
    "user:create": ("admin", "Crear usuarios"),
    "user:update": ("admin", "Modificar datos de usuarios"),
    "user:deactivate": ("admin", "Desactivar/reactivar usuarios"),
    "user:unlock": ("admin", "Desbloquear cuentas"),
    "user:reset_mfa": ("admin", "Restablecer factor MFA"),
    "role:read": ("admin", "Ver roles y permisos"),
    "role:assign": ("admin", "Solicitar asignación/retiro de roles (queda pendiente de aprobación)"),
    "role:approve": ("admin", "Aprobar o rechazar solicitudes de cambio de roles (doble control)"),
    "session:revoke": ("admin", "Revocar sesiones activas de un usuario"),
    "param:read": ("admin", "Ver parámetros del sistema"),
    "param:update": ("admin", "Modificar parámetros del sistema"),
    "backup:read": ("admin", "Ver estado de respaldos"),
    "backup:run": ("admin", "Ejecutar respaldo manual"),
    "backup:restore": ("admin", "Restaurar respaldo (doble control)"),
    "health:read": ("admin", "Ver salud del servidor y servicios"),
    # Ingesta
    "ingestion:upload": ("ingestion", "Cargar archivos de pólizas/siniestros/reservas"),
    "ingestion:read": ("ingestion", "Ver estado y resultados de cargas"),
    "ingestion:review_rejects": ("ingestion", "Revisar filas rechazadas"),
    "ingestion:cancel": ("ingestion", "Cancelar una carga en curso"),
    # Motor de auditoría
    "rule:read": ("audit_engine", "Ver reglas y parámetros"),
    "rule:configure": ("audit_engine", "Modificar umbrales/parámetros de reglas"),
    "rule:execute": ("audit_engine", "Ejecutar el motor de reglas"),
    "finding:read": ("audit_engine", "Ver hallazgos con detalle"),
    "finding:read_summary": ("audit_engine", "Ver hallazgos agregados (sin datos personales)"),
    "finding:triage": ("audit_engine", "Cambiar estado/asignar/comentar hallazgos"),
    "finding:escalate": ("audit_engine", "Escalar hallazgo a Contraloría"),
    "finding:close": ("audit_engine", "Cerrar hallazgo (falso positivo / resuelto)"),
    # Informes
    "report:draft": ("reporting", "Redactar providencias y dictámenes (borrador)"),
    "report:read": ("reporting", "Ver borradores y en revisión"),
    "report:read_approved": ("reporting", "Ver informes aprobados y firmados"),
    "report:submit": ("reporting", "Enviar borrador a aprobación"),
    "report:approve": ("reporting", "Aprobar o devolver informe"),
    "report:sign": ("reporting", "Firmar y sellar informe (requiere MFA reciente)"),
    "report:verify_signature": ("reporting", "Verificar firma/integridad de un PDF"),
    "report:export": ("reporting", "Exportar informes (PDF/Excel)"),
    "template:manage": ("reporting", "Gestionar plantillas de informes"),
    # Cumplimiento LC/FT y reportes regulatorios
    "lcft:alert_read": ("compliance", "Ver alertas LC/FT"),
    "lcft:alert_manage": ("compliance", "Analizar y gestionar alertas LC/FT"),
    "lcft:rule_configure": ("compliance", "Configurar reglas/umbrales LC/FT"),
    "regulatory:read": ("compliance", "Ver reportes regulatorios"),
    "regulatory:generate": ("compliance", "Generar reportes regulatorios"),
    "regulatory:approve": ("compliance", "Aprobar reporte regulatorio para envío"),
    # Analítica
    "dashboard:operational": ("analytics", "Ver dashboards operativos de auditoría"),
    "dashboard:executive": ("analytics", "Ver dashboards ejecutivos/KPIs"),
    "kpi:export": ("analytics", "Exportar KPIs"),
    # Auditorías (expedientes, cédulas, informes)
    "audit:read": ("engagement", "Ver expedientes, auditorías, cédulas y observaciones"),
    "audit:read_final": ("engagement", "Ver informes finales aprobados y firmados"),
    "audit:manage": ("engagement", "Crear expedientes y auditorías; trabajar cédulas, observaciones y evidencias"),
    "audit:rate": ("engagement", "Ajustar manualmente la calificación (a criterio del Auditor)"),
    "audit:template_manage": ("engagement", "Editar los criterios de las cédulas (plantillas)"),
    "audit:unit_manage": ("engagement", "Administrar el catálogo de unidades y sucursales"),
    "audit:report_draft": ("engagement", "Generar informes previos y finales (automático)"),
    "audit:report_submit": ("engagement", "Enviar el informe final al Contralor / el previo a la unidad"),
    "audit:report_approve": ("engagement", "Aprobar o devolver el informe final (Contralor)"),
    "audit:report_approve_jefe": ("engagement", "Aprobar o devolver el informe final como Jefe de Auditoría"),
    "audit:report_approve_gerente": ("engagement", "Aprobar y devolver el informe final como Gerencia"),
    "audit:initial": ("engagement", "Estampar las iniciales del auditor en el informe"),
    "audit:sign_contralor": ("engagement", "Firma electrónica del Contralor en el informe final"),
    "audit:sign_gerente": ("engagement", "Firma electrónica del Gerente de Control Interno"),
    "audit:pac_send": ("engagement", "Enviar el PAC (anexo en Excel) a la unidad"),
    "audit:general_read": ("engagement", "Acceso a auditorías generales existentes"),
    "audit:financial_read": ("engagement", "Acceso exclusivo a auditorías financieras"),
    "audit:financial_manage": ("engagement", "Crear y trabajar auditorías financieras"),
    "audit:financial_execute": ("engagement", "Pantalla operativa del Auditor Financiero"),
    "audit:financial_review": ("engagement", "Supervisar auditorías e informes financieros"),
    "audit:systems_read": ("engagement", "Acceso exclusivo a auditorías de sistemas/TI"),
    "audit:systems_manage": ("engagement", "Crear y trabajar auditorías de sistemas/TI"),
    "audit:systems_execute": ("engagement", "Pantalla operativa del Auditor de Sistemas"),
    "audit:systems_review": ("engagement", "Supervisar auditorías e informes de sistemas/TI"),
    # Trazabilidad
    "auditlog:read": ("audit_log", "Consultar el audit trail"),
    "auditlog:verify_chain": ("audit_log", "Verificar integridad de la cadena de hashes"),
    "auditlog:export": ("audit_log", "Exportar el audit trail"),
    # Propios de toda cuenta autenticada (no se listan por rol): perfil y MFA propio
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    SYS_ADMIN: {
        "user:read", "user:create", "user:update", "user:deactivate", "user:unlock",
        "user:reset_mfa", "role:read", "role:assign", "session:revoke",
        "param:read", "param:update",
        "backup:read", "backup:run", "backup:restore", "health:read",
        "auditlog:verify_chain",
    },
    AUDITOR: {
        "ingestion:upload", "ingestion:read", "ingestion:review_rejects", "ingestion:cancel",
        "rule:read", "rule:execute",
        "finding:read", "finding:triage", "finding:escalate",
        "report:draft", "report:read", "report:submit", "report:read_approved",
        "report:verify_signature", "report:export",
        "lcft:alert_read", "lcft:alert_manage",
        "regulatory:read", "regulatory:generate",
        "dashboard:operational",
        "audit:read", "audit:general_read", "audit:manage", "audit:rate", "audit:report_draft", "audit:report_submit",
        "audit:initial", "audit:pac_send", "audit:read_final",
    },
    CONTRALOR: {
        "ingestion:read", "ingestion:review_rejects",
        "rule:read", "rule:configure", "rule:execute",
        "finding:read", "finding:triage", "finding:close",
        "report:read", "report:read_approved", "report:approve", "report:sign",
        "report:verify_signature", "report:export", "template:manage",
        "lcft:alert_read", "lcft:alert_manage", "lcft:rule_configure",
        "regulatory:read", "regulatory:approve",
        "dashboard:operational", "dashboard:executive", "kpi:export",
        "role:read", "role:approve", "param:read",
        "auditlog:read", "auditlog:verify_chain", "auditlog:export",
        "audit:read", "audit:read_final", "audit:report_approve", "audit:sign_contralor",
        "audit:template_manage", "audit:unit_manage",
    },
    GERENCIA: {
        "finding:read_summary",
        "report:read_approved", "report:verify_signature",
        "dashboard:executive",
        "audit:read", "audit:read_final",
        "audit:sign_gerente", "audit:report_approve_gerente",
    },
    AUDITOR_FINANCIERO: {
        "ingestion:upload", "ingestion:read", "ingestion:review_rejects", "ingestion:cancel",
        "rule:read", "rule:execute", "finding:read", "finding:triage", "finding:escalate",
        "report:draft", "report:read", "report:submit", "report:read_approved", "report:verify_signature", "report:export",
        "dashboard:operational",
        "audit:read", "audit:manage", "audit:rate", "audit:report_draft", "audit:report_submit", "audit:initial", "audit:pac_send", "audit:read_final",
        "audit:financial_read", "audit:financial_manage", "audit:financial_execute",
    },
    JEFE_AUDITORIA_FINANCIERA: {
        "ingestion:read", "ingestion:review_rejects", "rule:read", "rule:execute",
        "finding:read", "finding:triage", "finding:escalate",
        "report:draft", "report:read", "report:submit", "report:read_approved", "report:verify_signature", "report:export",
        "dashboard:operational",
        "audit:read", "audit:manage", "audit:rate", "audit:report_draft", "audit:report_submit", "audit:initial", "audit:pac_send", "audit:read_final",
        "audit:financial_read", "audit:financial_manage", "audit:financial_review", "audit:report_approve_jefe",
    },
    AUDITOR_SISTEMAS: {
        "ingestion:upload", "ingestion:read", "ingestion:review_rejects", "ingestion:cancel",
        "rule:read", "rule:execute", "finding:read", "finding:triage", "finding:escalate",
        "report:draft", "report:read", "report:submit", "report:read_approved", "report:verify_signature", "report:export",
        "dashboard:operational",
        "audit:read", "audit:manage", "audit:rate", "audit:report_draft", "audit:report_submit", "audit:initial", "audit:pac_send", "audit:read_final",
        "audit:systems_read", "audit:systems_manage", "audit:systems_execute",
    },
    JEFE_AUDITORIA_SISTEMAS: {
        "ingestion:read", "ingestion:review_rejects", "rule:read", "rule:execute",
        "finding:read", "finding:triage", "finding:escalate",
        "report:draft", "report:read", "report:submit", "report:read_approved", "report:verify_signature", "report:export",
        "dashboard:operational",
        "audit:read", "audit:manage", "audit:rate", "audit:report_draft", "audit:report_submit", "audit:initial", "audit:pac_send", "audit:read_final",
        "audit:systems_read", "audit:systems_manage", "audit:systems_review", "audit:report_approve_jefe",
    },
}

# --------------------------------------------------- Segregación de funciones (SoD)
# Pares de permisos que NO deben coexistir en un mismo usuario (aunque tenga varios roles)
SOD_CONFLICTS: list[tuple[str, str, str]] = [
    ("report:draft", "report:approve", "Quien redacta no aprueba."),
    ("report:draft", "report:sign", "Quien redacta no firma."),
    ("ingestion:upload", "finding:close", "Quien carga datos no cierra hallazgos."),
    ("user:create", "auditlog:read", "Quien administra usuarios no consulta el audit trail."),
    ("backup:restore", "report:sign", "Quien restaura datos no firma informes."),
    ("param:update", "rule:configure", "Parámetros de plataforma y reglas de auditoría separados."),
    ("role:assign", "report:approve", "Quien asigna roles no aprueba informes."),
    ("role:assign", "role:approve", "Quien solicita un cambio de roles no lo aprueba."),
    ("user:create", "role:approve", "Quien crea usuarios no aprueba sus roles."),
    ("audit:manage", "audit:report_approve", "Quien ejecuta la auditoría no aprueba su informe."),
    ("audit:report_draft", "audit:sign_contralor", "Quien genera el informe no lo firma como Contralor."),
    ("audit:report_draft", "audit:sign_gerente", "Quien genera el informe no lo firma como Gerente de Control Interno."),
    ("audit:sign_contralor", "audit:sign_gerente", "Las dos firmas finales las ponen personas distintas."),
]


def permissions_for_roles(role_codes: list[str]) -> set[str]:
    perms: set[str] = set()
    for r in role_codes:
        perms |= ROLE_PERMISSIONS.get(r, set())
    return perms


def find_sod_violations(role_codes: list[str]) -> list[tuple[str, str, str]]:
    """Devuelve los conflictos SoD que generaría esta combinación de roles."""
    perms = permissions_for_roles(role_codes)
    return [c for c in SOD_CONFLICTS if c[0] in perms and c[1] in perms]


def _self_check() -> None:
    known = set(PERMISSIONS)
    for role, perms in ROLE_PERMISSIONS.items():
        unknown = perms - known
        assert not unknown, f"{role} usa permisos no definidos: {unknown}"
    for a, b, _ in SOD_CONFLICTS:
        assert a in known and b in known, f"SoD con permiso inexistente: {a}, {b}"
    for r in ROLES:
        assert not find_sod_violations([r]), f"El rol {r} viola SoD por sí mismo"


_self_check()
