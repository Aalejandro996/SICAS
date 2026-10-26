#!/bin/sh
# Punto de entrada de la imagen. Ejecuta el comando recibido tal cual.
#
# Render entrega el «Docker Command» de los servicios en segundo plano conservando las comillas
# simples literales (p. ej. sh -lc "'until ...; exec celery ...'"), y sh intenta ejecutar todo el
# texto como un único comando ("not found"). Si el último argumento de un «sh -c/-lc» viene
# envuelto en comillas simples, se le quitan antes de ejecutarlo.
set -e
if [ "$#" -eq 3 ] && { [ "$1" = "sh" ] || [ "$1" = "/bin/sh" ]; } && { [ "$2" = "-c" ] || [ "$2" = "-lc" ]; }; then
  script=$3
  case "$script" in
    \'*\') script=${script#\'}; script=${script%\'}; exec "$1" "$2" "$script" ;;
  esac
fi
exec "$@"
