-- 039: Informe general de auditorías (consolidado de varias auditorías en fase de Documentación o de Informe).
--
-- Flujo: el Auditor lo genera (borrador), lo firma y lo envía al Jefe de Auditoría de su dominio; el Jefe lo aprueba
-- o lo devuelve; aprobado, queda distribuido a Gerencia y al Contralor, que dejan constancia de su recepción.
-- El Auditor firma con sus iniciales (nombre y apellido); el Jefe, Gerencia y el Contralor estampan la firma escaneada
-- registrada en SICAS cada vez que aprueban. Todo queda atado al SHA-256 del contenido.

CREATE TABLE IF NOT EXISTS engagement.general_reports (
    id               UUID PRIMARY KEY,
    code             VARCHAR(30) NOT NULL UNIQUE,
    audit_domain     VARCHAR(12) NOT NULL CHECK (audit_domain IN ('GENERAL', 'FINANCIERA', 'SISTEMAS')),
    title            TEXT NOT NULL,
    status           VARCHAR(12) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'IN_REVIEW', 'RETURNED', 'APPROVED')),
    filters          JSONB NOT NULL DEFAULT '{}'::jsonb,
    audit_ids        UUID[] NOT NULL,
    body             JSONB NOT NULL,
    body_sha256      CHAR(64) NOT NULL,
    revision         INT NOT NULL DEFAULT 1,
    created_by       UUID NOT NULL REFERENCES iam.users(id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    auditor_signed_by     UUID REFERENCES iam.users(id),
    auditor_signed_at     TIMESTAMPTZ,
    auditor_signed_sha256 CHAR(64),
    auditor_signature_sha256 CHAR(64),
    jefe_by          UUID REFERENCES iam.users(id),
    jefe_at          TIMESTAMPTZ,
    jefe_sha256      CHAR(64),
    jefe_signature_sha256 CHAR(64),
    CHECK (cardinality(audit_ids) BETWEEN 1 AND 60)
);
CREATE INDEX IF NOT EXISTS general_reports_status ON engagement.general_reports (status, audit_domain);
CREATE INDEX IF NOT EXISTS general_reports_creator ON engagement.general_reports (created_by);

-- Bitácora del flujo: generación, regeneración, firma y envío, devolución, aprobación y acuses de recibo.
CREATE TABLE IF NOT EXISTS engagement.general_report_events (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id   UUID NOT NULL REFERENCES engagement.general_reports(id),
    action      VARCHAR(20) NOT NULL CHECK (action IN ('GENERATED', 'REGENERATED', 'SIGNED_SENT', 'RETURNED', 'APPROVED', 'ACKNOWLEDGED')),
    from_status VARCHAR(12),
    to_status   VARCHAR(12),
    body_sha256 CHAR(64) NOT NULL,
    actor_id    UUID NOT NULL REFERENCES iam.users(id),
    actor_role  VARCHAR(40),
    comment     TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS general_report_events_report ON engagement.general_report_events (report_id, id);

-- Recepción y conformidad de Gerencia y del Contralor, con su firma escaneada (una por persona).
CREATE TABLE IF NOT EXISTS engagement.general_report_acks (
    report_id   UUID NOT NULL REFERENCES engagement.general_reports(id),
    user_id     UUID NOT NULL REFERENCES iam.users(id),
    role        VARCHAR(20) NOT NULL CHECK (role IN ('GERENCIA', 'CONTRALOR')),
    body_sha256 CHAR(64) NOT NULL,
    signature_sha256 CHAR(64) NOT NULL,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (report_id, user_id)
);

GRANT SELECT, INSERT, UPDATE ON engagement.general_reports TO app_rw;
GRANT SELECT, INSERT ON engagement.general_report_events TO app_rw;
GRANT SELECT, INSERT ON engagement.general_report_acks TO app_rw;
