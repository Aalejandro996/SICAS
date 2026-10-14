#!/usr/bin/env python3
"""Genera Excel y HTML imprimible del mes calendario anterior.

Uso dentro del contenedor API:
  python scripts/generate_contralor_monthly_report.py
  python scripts/generate_contralor_monthly_report.py --output-dir /srv/data/engagement/contralor-reports
Los archivos HTML se pueden abrir e imprimir/guardar como PDF desde el navegador.
"""
from __future__ import annotations
import argparse
from datetime import date, timedelta
from pathlib import Path
from wsgi import app
from app.modules.analytics import contralor_service as service


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='/srv/data/engagement/contralor-reports')
    args = parser.parse_args()
    today = date.today()
    end = date(today.year, today.month, 1) - timedelta(days=1)
    start = date(end.year, end.month, 1)
    with app.app_context():
        filters = service.parse_filters({'start_date': start.isoformat(), 'end_date': end.isoformat(), 'granularity': 'MONTH'})
        data = service.get_dashboard_data(filters)
        kpis = service.list_kpis(as_of=end)
        data['historical_snapshots'] = service.list_dashboard_snapshots(12)
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"SICAS_Contralor_{start.year:04d}-{start.month:02d}"
        xlsx_path = out_dir / f"{stem}.xlsx"
        html_path = out_dir / f"{stem}.html"
        pdf_path = out_dir / f"{stem}.pdf"
        xlsx_path.write_bytes(service.export_workbook(data, kpis).getvalue())
        html_path.write_text(service.render_print_report(data, kpis), encoding='utf-8')
        pdf_path.write_bytes(service.export_pdf_report(data, kpis).getvalue())
        snapshot = service.create_dashboard_snapshot(filters, actor_id=None, source='AUTOMATICO')
        print(f"Excel: {xlsx_path}")
        print(f"Informe PDF: {pdf_path}")
        print(f"Informe imprimible: {html_path}")
        print(f"Corte histórico: {snapshot['id']}")

if __name__ == '__main__':
    main()
