"""
Revisión estática simple: nombres usados pero no definidos/importados en cada módulo (detecta errores de tipeo
y funciones que no existen). No reemplaza a un linter, pero no necesita instalar nada.
Uso: python scripts/check_names.py
"""
import ast
import builtins
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}


def defined_names(tree):
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
            if not isinstance(n, ast.ClassDef):
                a = n.args
                for arg in a.args + a.kwonlyargs + a.posonlyargs + ([a.vararg] if a.vararg else []) + ([a.kwarg] if a.kwarg else []):
                    names.add(arg.arg)
        elif isinstance(n, ast.Lambda):
            for arg in n.args.args + n.args.kwonlyargs:
                names.add(arg.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                names.add((al.asname or al.name).split(".")[0])
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            names.update(n.names)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
    return names


bad = 0
for path in sorted(ROOT.rglob("*.py")):
    if any(p in path.parts for p in (".venv", "__pycache__", "secrets")):
        continue
    tree = ast.parse(path.read_text(encoding="utf-8"))
    known = defined_names(tree) | BUILTINS
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in known:
            print(f"{path.relative_to(ROOT)}:{n.lineno}: nombre no definido '{n.id}'")
            bad += 1
print("Sin nombres indefinidos." if not bad else f"\n{bad} posible(s) problema(s).")
sys.exit(1 if bad else 0)
