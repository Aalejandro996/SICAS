#!/bin/sh
# Worker de Celery: espera a que Render monte los secretos del checkpoint y arranca.
set -e
until [ -r /etc/secrets/checkpoint_private.pem ] && [ -r /etc/secrets/checkpoint_public.pem ]; do sleep 10; done
exec celery -A celery_worker.celery worker -Q ingestion,reports,alerts -c 2 --loglevel=INFO
