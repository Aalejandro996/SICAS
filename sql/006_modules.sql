-- 006: Parámetros del sistema, respaldos y folios de informes
CREATE SCHEMA IF NOT EXISTS admin;

CREATE TABLE admin.system_params (
    key        VARCHAR(60) PRIMARY KEY,
    value      JSONB NOT NULL,
    updated_by UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin.backups (
    id           UUID PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       VARCHAR(10) NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','OK','FAILED')),
    file_path    TEXT, size_bytes BIGINT, sha256 CHAR(64),
    requested_by UUID, error TEXT
);

CREATE SEQUENCE IF NOT EXISTS reporting.folio_seq;
ALTER TABLE reporting.reports
    ADD COLUMN IF NOT EXISTS folio VARCHAR(30) UNIQUE,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

GRANT USAGE ON SCHEMA admin TO app_rw;
GRANT SELECT, INSERT, UPDATE ON admin.system_params, admin.backups TO app_rw;
GRANT USAGE ON SEQUENCE reporting.folio_seq TO app_rw;
