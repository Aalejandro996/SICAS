# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --create-home --uid 10001 app \
    && (getent group 1000 >/dev/null || groupadd --gid 1000 rendersecrets) \
    && usermod --append --groups "$(getent group 1000 | cut -d: -f1)" app
WORKDIR /srv
COPY requirements/base.txt requirements/base.txt
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --retries 10 --timeout 300 -r requirements/base.txt boto3
COPY --chown=app:app . .
RUN mkdir -p /srv/data/engagement \
    && chown -R app:app /srv/data
USER app
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8000", "--access-logfile", "-", "wsgi:app"]
