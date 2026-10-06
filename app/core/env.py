"""Carga el archivo .env (solo desarrollo). En producción las variables vienen del orquestador/Vault."""
import os
import pathlib


def load_dotenv_file(path: str | None = None) -> None:
    p = pathlib.Path(path) if path else pathlib.Path(__file__).resolve().parents[2] / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
