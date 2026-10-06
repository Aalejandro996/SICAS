"""
Aplica los scripts de sql/ que falten, en orden, y registra cuáles ya se aplicaron.
Uso:  python scripts/migrate.py            (usa DATABASE_URL del .env)
- Si la base ya tenía 000-005 aplicados a mano (antes de existir este script), los reconoce y no los repite.
- Los archivos *_seed.sql son idempotentes y se vuelven a aplicar siempre (permisos nuevos).
- Cada archivo se ejecuta en una transacción: si falla, no queda a medias.
"""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.env import load_dotenv_file  # noqa: E402


def main():
    load_dotenv_file()
    import psycopg

    url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if not url:
        sys.exit("Falta DATABASE_URL (ejecute primero scripts/init_env.py)")
    files = sorted((ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql"))
    with psycopg.connect(url, autocommit=True) as cx:
        cx.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        done = {r[0] for r in cx.execute("SELECT filename FROM public.schema_migrations")}
        if not done and cx.execute("SELECT to_regclass('iam.users')").fetchone()[0]:
            legacy = [f.name for f in files if f.name < "006"]          # base creada a mano con 000-005
            for n in legacy:
                cx.execute("INSERT INTO public.schema_migrations (filename) VALUES (%s) ON CONFLICT DO NOTHING", (n,))
            done = set(legacy)
            print(f"Base existente reconocida: {len(legacy)} scripts previos marcados como aplicados.")
        pending = [f for f in files if f.name not in done or f.name.endswith("_seed.sql")]
        if not pending:
            print("Nada pendiente: la base está al día."); return
        for f in pending:
            print(f"Aplicando {f.name} ...", end=" ", flush=True)
            try:
                with cx.transaction():
                    cx.execute(f.read_text(encoding="utf-8"))
                    cx.execute("INSERT INTO public.schema_migrations (filename) VALUES (%s) ON CONFLICT (filename) DO UPDATE SET applied_at = now()", (f.name,))
                print("OK")
            except Exception as e:  # noqa: BLE001
                print("ERROR")
                sys.exit(f"\nFalló {f.name}: {e}\n\nNo se aplicó nada de ese archivo. Corrija y vuelva a ejecutar.")
    print("Base de datos al día.")


if __name__ == "__main__":
    main()
