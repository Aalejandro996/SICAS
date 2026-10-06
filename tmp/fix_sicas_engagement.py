#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys
import ast

ROOT = Path.cwd()
REPO = ROOT / "app/modules/engagement/repositories.py"
API = ROOT / "app/modules/engagement/api.py"

if not REPO.exists():
    print("ERROR: no existe:", REPO)
    sys.exit(1)

def functions_in(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

def backup(path):
    b = path.with_name(path.name + ".bak_before_engagement_fix")
    if not b.exists():
        shutil.copy2(path, b)
        print("Backup creado:", b)
    else:
        print("Backup ya existe:", b)

source = REPO.read_text(encoding="utf-8")
existing = functions_in(REPO)

required = {
    "team",
    "is_member",
    "my_audit_ids",
    "eligible_auditors",
    "create_audit",
}
missing = sorted(required - existing)

if missing:
    marker = "\ndef change_phase("
    if marker not in source:
        print("ERROR: no se encontró def change_phase().")
        print("No se modificó repositories.py.")
        sys.exit(2)

    block = r