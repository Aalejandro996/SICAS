-- 002: Datos de negocio mínimos, motor de anomalías, informes y firma
CREATE SCHEMA IF NOT EXISTS insurance;
CREATE SCHEMA IF NOT EXISTS engine;
CREATE SCHEMA IF NOT EXISTS reporting;

-- ---------- Ingesta ----------
CREATE TABLE insurance.ingestion_jobs (
    id            UUID PRIMARY KEY,
    dataset       VARCHAR(20) NOT NULL CHECK (dataset IN ('policies','claims','reserves','payments')),
    sha256        CHAR(64)    NOT NULL,
    object_key    TEXT        NOT NULL,
    status        VARCHAR(12) NOT NULL DEFAULT 'QUEUED'
                  CHECK (status IN ('QUEUED','PROCESSING','COMPLETED','FAILED','CANCELLED')),
    rows_total    INT, rows_processed INT DEFAULT 0, rows_rejected INT DEFAULT 0,
    -- Totales de control: lo leído del archivo debe coincidir con lo cargado (ver reconcile.py)
    control_rows  INT, control_amount NUMERIC(24,2), control_hash CHAR(64), reconciled BOOLEAN,
    uploaded_by   UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    UNIQUE (dataset, sha256)                                -- idempotencia por archivo
);

-- Las tablas de negocio son COPIA FIEL de lo recibido: no imponen unicidad de claves de negocio,
-- para que el motor pueda DETECTAR duplicados en lugar de que la base los oculte o los rechace.
CREATE TABLE insurance.policies (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    policy_number  VARCHAR(40) NOT NULL,
    insured_id     VARCHAR(30) NOT NULL,                    -- cédula/RIF (cifrar a nivel de columna / índice ciego)
    risk_id        VARCHAR(60),
    branch         VARCHAR(30) NOT NULL,
    start_date     DATE NOT NULL, end_date DATE NOT NULL,
    sum_insured    NUMERIC(18,2) NOT NULL CHECK (sum_insured >= 0),
    premium        NUMERIC(18,2) NOT NULL CHECK (premium >= 0),
    currency       CHAR(3) NOT NULL CHECK (currency IN ('VES','USD','EUR')),
    status         VARCHAR(15) NOT NULL DEFAULT 'ACTIVE',
    job_id         UUID REFERENCES insurance.ingestion_jobs(id),
    CHECK (end_date > start_date)
);
CREATE INDEX ON insurance.policies (policy_number);
CREATE INDEX ON insurance.policies (insured_id, risk_id);

CREATE TABLE insurance.claims (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    claim_number    VARCHAR(40) NOT NULL,
    policy_number   VARCHAR(40) NOT NULL,                   -- sin FK: un siniestro huérfano también es hallazgo
    coverage        VARCHAR(40),
    occurrence_date DATE NOT NULL, reported_date DATE NOT NULL,
    claimed_amount  NUMERIC(18,2) NOT NULL,
    currency        CHAR(3) NOT NULL CHECK (currency IN ('VES','USD','EUR')),
    status          VARCHAR(15) NOT NULL DEFAULT 'OPEN',
    job_id          UUID REFERENCES insurance.ingestion_jobs(id)
);
CREATE INDEX ON insurance.claims (claim_number);
CREATE INDEX ON insurance.claims (policy_number, occurrence_date);

CREATE TABLE insurance.reserves (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    reserve_type  VARCHAR(20) NOT NULL CHECK (reserve_type IN ('CLAIM','MATHEMATICAL','UNEARNED_PREMIUM')),
    branch        VARCHAR(30) NOT NULL,
    policy_number VARCHAR(40), claim_number VARCHAR(40),
    period        DATE NOT NULL,
    amount        NUMERIC(18,2) NOT NULL,
    sum_insured   NUMERIC(18,2),
    currency      CHAR(3) NOT NULL CHECK (currency IN ('VES','USD','EUR')),
    job_id        UUID REFERENCES insurance.ingestion_jobs(id)
);

CREATE TABLE insurance.payments (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payment_id    VARCHAR(40) NOT NULL,
    policy_number VARCHAR(40) NOT NULL,
    payer_id      VARCHAR(30) NOT NULL,
    amount        NUMERIC(18,2) NOT NULL CHECK (amount > 0),
    currency      CHAR(3) NOT NULL CHECK (currency IN ('VES','USD','EUR')),
    method        VARCHAR(12) NOT NULL CHECK (method IN ('CASH','TRANSFER','CARD','CHECK','OTHER')),
    paid_at       DATE NOT NULL,
    job_id        UUID REFERENCES insurance.ingestion_jobs(id)
);
CREATE INDEX ON insurance.payments (payer_id, paid_at);

CREATE TABLE insurance.ingestion_rejects (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES insurance.ingestion_jobs(id),
    line_no INT NOT NULL, errors JSONB NOT NULL
);

-- ---------- Staging: texto tal cual llega; se valida y promueve en una transacción ----------
CREATE SCHEMA IF NOT EXISTS staging;
CREATE TABLE staging.policies (job_id UUID NOT NULL, policy_number TEXT, insured_id TEXT, risk_id TEXT, branch TEXT,
    start_date TEXT, end_date TEXT, sum_insured TEXT, premium TEXT, currency TEXT);
CREATE TABLE staging.claims (job_id UUID NOT NULL, claim_number TEXT, policy_number TEXT, coverage TEXT,
    occurrence_date TEXT, reported_date TEXT, claimed_amount TEXT, currency TEXT);
CREATE TABLE staging.reserves (job_id UUID NOT NULL, reserve_type TEXT, branch TEXT, policy_number TEXT,
    claim_number TEXT, period TEXT, amount TEXT, sum_insured TEXT, currency TEXT);
CREATE TABLE staging.payments (job_id UUID NOT NULL, payment_id TEXT, policy_number TEXT, payer_id TEXT,
    amount TEXT, currency TEXT, method TEXT, paid_at TEXT);
CREATE INDEX ON staging.policies (job_id); CREATE INDEX ON staging.claims (job_id);
CREATE INDEX ON staging.reserves (job_id); CREATE INDEX ON staging.payments (job_id);

-- ---------- Motor de reglas ----------
CREATE TABLE engine.rule_parameters (
    rule_code   VARCHAR(40) PRIMARY KEY,
    params      JSONB NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by  UUID, updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE engine.runs (
    id UUID PRIMARY KEY, job_id UUID, started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ, status VARCHAR(12) NOT NULL DEFAULT 'RUNNING',
    triggered_by UUID, params_snapshot JSONB NOT NULL      -- parámetros usados: reproducibilidad
);

CREATE TABLE engine.findings (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       UUID NOT NULL REFERENCES engine.runs(id),
    rule_code    VARCHAR(40) NOT NULL,
    severity     VARCHAR(8)  NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    entity_type  VARCHAR(30) NOT NULL, entity_id TEXT NOT NULL,
    score        NUMERIC(6,2) NOT NULL,
    message      TEXT NOT NULL, evidence JSONB NOT NULL,
    fingerprint  CHAR(64) NOT NULL,                        -- hash(rule_code, entidad, hechos) -> dedupe
    status       VARCHAR(12) NOT NULL DEFAULT 'OPEN'
                 CHECK (status IN ('OPEN','IN_REVIEW','ESCALATED','CLOSED_FP','CLOSED_RESOLVED')),
    assigned_to  UUID, closed_by UUID, closed_reason TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fingerprint)
);
CREATE INDEX ON engine.findings (status, severity);
CREATE INDEX ON engine.findings (entity_type, entity_id);

-- ---------- Informes y firma ----------
CREATE TABLE reporting.reports (
    id           UUID PRIMARY KEY,
    kind         VARCHAR(20) NOT NULL CHECK (kind IN ('DICTAMEN','PROVIDENCIA','REGULATORIO')),
    title        TEXT NOT NULL, body JSONB NOT NULL,
    status       VARCHAR(12) NOT NULL DEFAULT 'DRAFT'
                 CHECK (status IN ('DRAFT','SUBMITTED','RETURNED','APPROVED','SIGNED')),
    drafted_by   UUID NOT NULL, submitted_at TIMESTAMPTZ,
    approved_by  UUID, approved_at TIMESTAMPTZ,
    approved_body_sha256 CHAR(64),                  -- hash del contenido al aprobar
    return_reason TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (approved_by IS NULL OR approved_by <> drafted_by)     -- doble control
);

-- Registro de documentos firmados (solo INSERT; sin UPDATE/DELETE)
CREATE TABLE reporting.signed_documents (
    id               UUID PRIMARY KEY,
    report_id        UUID NOT NULL REFERENCES reporting.reports(id),
    version          INT  NOT NULL DEFAULT 1,
    sha256_unsigned  CHAR(64) NOT NULL,
    sha256_signed    CHAR(64) NOT NULL,
    object_key       TEXT NOT NULL,
    signer_user_id   UUID NOT NULL,
    signer_subject   TEXT NOT NULL,               -- DN del certificado
    cert_serial      TEXT NOT NULL, cert_sha256 CHAR(64) NOT NULL,
    signed_at        TIMESTAMPTZ NOT NULL,
    tsa_url          TEXT, timestamp_embedded BOOLEAN NOT NULL DEFAULT FALSE,
    signature_level  VARCHAR(20) NOT NULL DEFAULT 'PADES-B-T',
    UNIQUE (report_id, version)
);

CREATE OR REPLACE FUNCTION reporting.fn_block_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'signed_documents es de solo inserción'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_signed_immutable BEFORE UPDATE OR DELETE ON reporting.signed_documents
    FOR EACH ROW EXECUTE FUNCTION reporting.fn_block_mutation();
