#!/usr/bin/env python3
from pathlib import Path
import ast
import shutil
import sys

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "app/modules/engagement/repositories.py"

REQUIRED = {
    "team",
    "is_member",
    "my_audit_ids",
    "eligible_auditors",
    "create_audit",
}

if not TARGET.exists():
    print(f"ERROR: no existe {TARGET}")
    sys.exit(1)

source = TARGET.read_text(encoding="utf-8")

try:
    tree = ast.parse(source)
except SyntaxError as e:
    print(f"ERROR: repositories.py tiene un error de sintaxis: {e}")
    sys.exit(2)

existing = {
    node.name
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
}

print("Funciones requeridas:")
for name in sorted(REQUIRED):
    print(f"  {'OK' if name in existing else 'FALTA'} {name}")

missing = REQUIRED - existing

if not missing:
    print("\nNo faltan las funciones requeridas.")
    print("No se modificó repositories.py.")
    sys.exit(0)

# No sobrescribir un backup anterior.
backup = TARGET.with_suffix(".py.bak_before_restore_complete")
if not backup.exists():
    shutil.copy2(TARGET, backup)
    print(f"\nBackup creado: {backup}")
else:
    print(f"\nBackup ya existente: {backup}")

BLOCKS = {}

BLOCKS["team"] = 