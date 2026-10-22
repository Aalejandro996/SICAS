"""
Carga unidades/sucursales de EJEMPLO para poder crear expedientes (desarrollo). Cámbielas por las reales desde
Auditorías -> Unidades y sucursales. No crea usuarios (use scripts/bootstrap_admin.py y la pantalla de Usuarios).
Uso:  python scripts/seed_dev.py
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.env import load_dotenv_file  # noqa: E402

UNITS = [("SUC-CENTRO", "Sucursal Centro", "SUCURSAL"), ("SUC-ESTE", "Sucursal Este", "SUCURSAL"),
         ("SUC-OESTE", "Sucursal Oeste", "SUCURSAL"), ("UND-SINIESTROS", "Unidad de Siniestros", "UNIDAD"),
         ("UND-SUSCRIPCION", "Unidad de Suscripción", "UNIDAD")]

load_dotenv_file()
import psycopg  # noqa: E402

url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://", 1)
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]
if not url:
    sys.exit("Falta DATABASE_URL")
with psycopg.connect(url) as cx:
    for code, name, kind in UNITS:
        cx.execute("INSERT INTO engagement.units (code, name, kind) VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING", (code, name, kind))
print(f"{len(UNITS)} unidades de ejemplo disponibles.")
