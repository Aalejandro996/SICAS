"""Genera sql/003_rbac_seed.sql y docs/RBAC_MATRIX.md desde app/core/security/permissions.py"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.security import permissions as P  # noqa: E402

MODULE_TITLES = {
    "admin": "Administración y Sistemas", "ingestion": "Ingesta de datos",
    "audit_engine": "Motor de auditoría", "reporting": "Informes y firma",
    "compliance": "Cumplimiento LC/FT y regulatorio", "analytics": "Analítica",
    "audit_log": "Audit trail", "engagement": "Auditorías (expedientes, cédulas, informes)",
}
ROLE_ORDER = [P.SYS_ADMIN, P.AUDITOR, P.CONTRALOR, P.GERENCIA]


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def build_sql() -> str:
    out = ["-- GENERADO por scripts/generate_rbac_seed.py. No editar a mano.", "BEGIN;"]
    for code, desc in P.ROLES.items():
        out.append(f"INSERT INTO iam.roles(code, description) VALUES ({q(code)}, {q(desc)}) "
                   "ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description;")
    for code, (mod, desc) in P.PERMISSIONS.items():
        out.append(f"INSERT INTO iam.permissions(code, module, description) VALUES ({q(code)}, {q(mod)}, {q(desc)}) "
                   "ON CONFLICT (code) DO UPDATE SET module = EXCLUDED.module, description = EXCLUDED.description;")
    for role, perms in P.ROLE_PERMISSIONS.items():
        for perm in sorted(perms):
            out.append("INSERT INTO iam.role_permissions(role_id, permission_id) "
                       f"SELECT r.id, p.id FROM iam.roles r, iam.permissions p WHERE r.code={q(role)} AND p.code={q(perm)} "
                       "ON CONFLICT DO NOTHING;")
    for a, b, why in P.SOD_CONFLICTS:
        out.append(f"INSERT INTO iam.sod_conflicts(permission_a, permission_b, reason) VALUES ({q(a)}, {q(b)}, {q(why)}) "
                   "ON CONFLICT DO NOTHING;")
    out.append("COMMIT;")
    return "\n".join(out) + "\n"


def build_md() -> str:
    lines = ["# Matriz RBAC", "", "Generada automáticamente desde `app/core/security/permissions.py`.",
             "Leyenda: ● permitido · (vacío) denegado.", ""]
    lines += ["## Roles", "", "| Rol | Propósito |", "|---|---|"]
    for r in ROLE_ORDER:
        lines.append(f"| {r} | {P.ROLES[r]} |")
    by_mod: dict[str, list[str]] = {}
    for code, (mod, _) in P.PERMISSIONS.items():
        by_mod.setdefault(mod, []).append(code)
    for mod, codes in by_mod.items():
        lines += ["", f"## {MODULE_TITLES[mod]}", "",
                  "| Permiso | Descripción | " + " | ".join(ROLE_ORDER) + " |",
                  "|---|---|" + "---|" * len(ROLE_ORDER)]
        for c in codes:
            marks = ["●" if c in P.ROLE_PERMISSIONS[r] else "" for r in ROLE_ORDER]
            lines.append(f"| `{c}` | {P.PERMISSIONS[c][1]} | " + " | ".join(marks) + " |")
    lines += ["", "## Segregación de funciones (SoD)", "",
              "Ningún usuario puede acumular ambos permisos de un par. El servicio de asignación de roles "
              "rechaza la combinación y registra el intento en el audit trail.", "",
              "| Permiso A | Permiso B | Motivo |", "|---|---|---|"]
    for a, b, why in P.SOD_CONFLICTS:
        lines.append(f"| `{a}` | `{b}` | {why} |")
    lines += ["", "## Reglas adicionales (no expresables solo con permisos)", "",
              "- **Doble control:** el aprobador de un informe debe ser distinto de su redactor (`approved_by <> drafted_by`).",
              "- **Firma:** exige MFA reciente (step-up, máx. 5 min) además del permiso `report:sign`.",
              "- **Combinación de roles:** `find_sod_violations()` se ejecuta al asignar roles.",
              "- **Restauración de respaldos y cambio de roles:** requieren segunda aprobación de otro usuario con permiso equivalente.",
              "- **GERENCIA** nunca ve datos personales de asegurados: solo agregados e informes aprobados.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    (ROOT / "sql" / "003_rbac_seed.sql").write_text(build_sql(), encoding="utf-8")
    (ROOT / "docs" / "RBAC_MATRIX.md").write_text(build_md(), encoding="utf-8")
    print("OK: sql/003_rbac_seed.sql y docs/RBAC_MATRIX.md generados")
