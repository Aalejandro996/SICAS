#!/bin/sh
# Instala/elimina LaunchAgents del usuario para cortes diarios y reporte mensual.
# No se activan durante la instalación del paquete; el usuario ejecuta este script.
set -eu
ACTION="${1:-install}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOCKER_BIN="$(command -v docker || true)"
UID_NUM="$(id -u)"
PLIST_MONTHLY="$HOME/Library/LaunchAgents/com.sicas.contralor.monthly-report.plist"
PLIST_DAILY="$HOME/Library/LaunchAgents/com.sicas.contralor.daily-snapshot.plist"
LOG_DIR="$HOME/SICAS-backups"
mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

case "$ACTION" in
  install)
    if [ -z "$DOCKER_BIN" ]; then
      echo "ERROR: no se encuentra docker en PATH." >&2
      exit 1
    fi
    ROOT="$ROOT" DOCKER_BIN="$DOCKER_BIN" PLIST_MONTHLY="$PLIST_MONTHLY" PLIST_DAILY="$PLIST_DAILY" LOG_DIR="$LOG_DIR" python3 - <<'PY'
import os, plistlib
from pathlib import Path
root=Path(os.environ['ROOT']).resolve()
docker=os.environ['DOCKER_BIN']
compose=str(root/'infra/docker/docker-compose.yml')
log=Path(os.environ['LOG_DIR'])
shared={'WorkingDirectory':str(root),'RunAtLoad':False}
monthly={**shared,
 'Label':'com.sicas.contralor.monthly-report',
 'ProgramArguments':[docker,'compose','-f',compose,'run','--rm','--no-deps','api','python','scripts/generate_contralor_monthly_report.py'],
 'StartCalendarInterval':{'Day':1,'Hour':7,'Minute':10},
 'StandardOutPath':str(log/'contralor-monthly-report.log'),
 'StandardErrorPath':str(log/'contralor-monthly-report.error.log'),
}
daily={**shared,
 'Label':'com.sicas.contralor.daily-snapshot',
 'ProgramArguments':[docker,'compose','-f',compose,'run','--rm','--no-deps','api','python','scripts/capture_contralor_snapshot.py'],
 'StartCalendarInterval':{'Hour':23,'Minute':50},
 'StandardOutPath':str(log/'contralor-daily-snapshot.log'),
 'StandardErrorPath':str(log/'contralor-daily-snapshot.error.log'),
}
Path(os.environ['PLIST_MONTHLY']).write_bytes(plistlib.dumps(monthly,fmt=plistlib.FMT_XML,sort_keys=True))
Path(os.environ['PLIST_DAILY']).write_bytes(plistlib.dumps(daily,fmt=plistlib.FMT_XML,sort_keys=True))
PY
    for PLIST in "$PLIST_MONTHLY" "$PLIST_DAILY"; do
      LABEL="$(/usr/libexec/PlistBuddy -c 'Print :Label' "$PLIST")"
      launchctl bootout "gui/$UID_NUM" "$PLIST" >/dev/null 2>&1 || true
      launchctl bootstrap "gui/$UID_NUM" "$PLIST"
      echo "LaunchAgent instalado: $LABEL"
    done
    echo "Cortes diarios: 23:50 hora local del Mac. Reporte del mes anterior: día 1 a las 07:10."
    echo "Necesitan Docker Desktop y los servicios SICAS (incluido PostgreSQL) en ejecución."
    echo "Logs: $LOG_DIR/contralor-*.log y archivos .error.log"
    ;;
  uninstall)
    launchctl bootout "gui/$UID_NUM" "$PLIST_MONTHLY" >/dev/null 2>&1 || true
    launchctl bootout "gui/$UID_NUM" "$PLIST_DAILY" >/dev/null 2>&1 || true
    rm -f "$PLIST_MONTHLY" "$PLIST_DAILY"
    echo "LaunchAgents de Contraloría eliminados."
    ;;
  *)
    echo "Uso: $0 [install|uninstall]" >&2
    exit 2
    ;;
esac
