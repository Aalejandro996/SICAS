#!/usr/bin/env python3
"""Verificacion de solo lectura para el paso 1 de SICAS."""
from __future__ import annotations

import sys

from sqlalchemy import text

from app import create_app
from app.extensions import db

EXPECTED_BRANCHES = 25
EXPECTED_TEMPLATES = 8
EXPECTED_CRITERIA = 113
EXPECTED_SIGNATURES = 16


def main() -> int:
    app = create_app()
    with app.app_context():
        checks = [
            ("sucursales activas catalogadas", "SELECT count(*) FROM engagement.units WHERE kind='SUCURSAL' AND active", EXPECTED_BRANCHES),
            ("grupos financieros", "SELECT count(*) FROM engagement.financial_templates WHERE active", EXPECTED_TEMPLATES),
            ("criterios financieros", "SELECT count(*) FROM engagement.financial_criteria", EXPECTED_CRITERIA),
            ("firmas activas", "SELECT count(*) FROM engagement.signature_assets WHERE active", EXPECTED_SIGNATURES),
        ]
        ok = True
        for label, sql, expected in checks:
            actual = db.session.execute(text(sql)).scalar_one()
            passed = actual == expected
            ok &= passed
            print(f"{'OK' if passed else 'ERROR'} | {label}: {actual} (esperado {expected})")

        print("--- dominios financieros ---")
        rows = db.session.execute(text("""
            SELECT code, kind, COALESCE(line, '—') AS line,
                   (SELECT count(*) FROM engagement.financial_criteria c WHERE c.template_code=t.code) AS criteria
            FROM engagement.financial_templates t
            ORDER BY code
        """)).mappings().all()
        for row in rows:
            print(f"{row['code']} | {row['kind']} | {row['line']} | {row['criteria']}")

        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
