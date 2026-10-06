#!/usr/bin/env python3

import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime

COMPOSE = [
    "docker", "compose",
    "-f", "infra/docker/docker-compose.yml"
]

URL = "https://localhost/"
CHECK_EVERY = 15
FAILURES_BEFORE_RESTART = 2


def log(message):
    print(
        f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
        f"{message}",
        flush=True
    )


def check_api():
    try:
        request = urllib.request.Request(
            URL,
            headers={"User-Agent": "SICAS-watchdog"}
        )

        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:
            return response.status

    except urllib.error.HTTPError as e:
        return e.code

    except Exception as e:
        log(f"Error comprobando SICAS: {e}")
        return None


def restart():
    log("Reiniciando API y Nginx...")

    subprocess.run(
        COMPOSE + ["restart", "api", "nginx"],
        check=False
    )

    log("Reinicio ejecutado.")


def main():
    log("SICAS watchdog iniciado.")
    log(f"Comprobando {URL} cada {CHECK_EVERY} segundos.")

    failures = 0

    while True:
        status = check_api()

        if status == 502:
            failures += 1
            log(
                f"HTTP 502 detectado "
                f"({failures}/{FAILURES_BEFORE_RESTART})"
            )

            if failures >= FAILURES_BEFORE_RESTART:
                restart()
                failures = 0

                # Dar tiempo a Gunicorn/Nginx para arrancar.
                time.sleep(20)

        elif status is None:
            failures += 1
            log(
                f"No se pudo contactar SICAS "
                f"({failures}/{FAILURES_BEFORE_RESTART})"
            )

            if failures >= FAILURES_BEFORE_RESTART:
                restart()
                failures = 0
                time.sleep(20)

        else:
            if failures:
                log(f"SICAS recuperado. HTTP {status}")

            failures = 0

        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    main()