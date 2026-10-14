#!/usr/bin/env python3
"""Captura un corte agregado del dashboard en analytics.dashboard_snapshots.

Ejecutar dentro del contenedor API después de migración 015:
  python scripts/capture_contralor_snapshot.py
La tarea no modifica auditorías ni observaciones; solo añade un corte inmutable.
"""
from __future__ import annotations

from wsgi import app
from app.modules.analytics import contralor_service as service


def main() -> None:
    with app.app_context():
        filters = service.parse_filters({})
        snapshot = service.create_dashboard_snapshot(filters, actor_id=None, source="AUTOMATICO")
        print(f"Corte SICAS creado: {snapshot['id']} ({snapshot['snapshot_date']})")


if __name__ == "__main__":
    main()
