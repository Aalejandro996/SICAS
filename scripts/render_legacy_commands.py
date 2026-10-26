"""Hace ejecutables los «Docker Command» que hoy tienen sicas-worker y sicas-beat en Render.

Render entrega esos comandos como  sh -lc "'until ...; exec celery ...'"  (con las comillas simples
literales), y sh interpreta todo el texto como el nombre de UN comando. Como ese texto contiene «/»,
sh lo busca como ruta relativa al directorio de trabajo (/srv). Este script crea, durante la
construcción de la imagen, un ejecutable en exactamente esa ruta que arranca el servicio correcto.

Es un puente temporal: al cambiar el Docker Command en Render por
    sh /srv/infra/docker/start-worker.sh      (sicas-worker)
    sh /srv/infra/docker/start-beat.sh        (sicas-beat)
deja de usarse y puede eliminarse.
"""
import os
import pathlib
import sys

WAIT = "until [ -r /etc/secrets/checkpoint_private.pem ] && [ -r /etc/secrets/checkpoint_public.pem ]; do sleep 10; done; "
COMMANDS = {
    WAIT + "exec celery -A celery_worker.celery worker -Q ingestion,reports,alerts -c 2 --loglevel=INFO": "start-worker.sh",
    WAIT + "exec celery -A celery_worker.celery beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule": "start-beat.sh",
}


def main(root: str) -> None:
    for command, script in COMMANDS.items():
        target = pathlib.Path(root, command)          # ruta relativa a /srv, igual que la resuelve sh
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"#!/bin/sh\nexec sh {root}/infra/docker/{script}\n", encoding="utf-8")
        os.chmod(target, 0o755)
        print(f"{script}: {target}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/srv")
