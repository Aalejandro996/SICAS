#!/bin/sh
# Planificador de Celery (beat): espera a que Render monte los secretos del checkpoint y arranca.
set -e
until [ -r /etc/secrets/checkpoint_private.pem ] && [ -r /etc/secrets/checkpoint_public.pem ]; do sleep 10; done
exec celery -A celery_worker.celery beat --loglevel=INFO --schedule=/tmp/celerybeat-schedule
