-- 007: Auditorías — expedientes, fases, cédulas, observaciones, evidencias, informes y firmas
CREATE SCHEMA IF NOT EXISTS engagement;

CREATE TABLE engagement.units (
    id     SERIAL PRIMARY KEY,
    code   VARCHAR(20) NOT NULL UNIQUE,
    name   VARCHAR(120) NOT NULL,
    kind   VARCHAR(10) NOT NULL CHECK (kind IN ('SUCURSAL','UNIDAD')),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE SEQUENCE engagement.file_seq;
CREATE SEQUENCE engagement.audit_seq;

-- 7.1 Primero se crea el expediente
CREATE TABLE engagement.files (
    id          UUID PRIMARY KEY,
    code        VARCHAR(20) NOT NULL UNIQUE,
    unit_id     INT NOT NULL REFERENCES engagement.units(id),
    title       TEXT NOT NULL,
    objective   TEXT,
    period_from DATE NOT NULL, period_to DATE NOT NULL,
    status      VARCHAR(8) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','CLOSED')),
    created_by  UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (period_to >= period_from)
);

-- 7.2 Formulario de auditoría: remota o presencial
CREATE TABLE engagement.audits (
    id            UUID PRIMARY KEY,
    code          VARCHAR(20) NOT NULL UNIQUE,
    file_id       UUID NOT NULL REFERENCES engagement.files(id),
    modality      VARCHAR(10) NOT NULL CHECK (modality IN ('REMOTA','PRESENCIAL')),
    phase         VARCHAR(14) NOT NULL DEFAULT 'PLANIFICACION' CHECK (phase IN ('PLANIFICACION','TRABAJO_CAMPO','INFORME')),
    status        VARCHAR(12) NOT NULL DEFAULT 'IN_PROGRESS' CHECK (status IN ('IN_PROGRESS','CLOSED')),
    objectives    TEXT NOT NULL, scope TEXT NOT NULL, procedures TEXT,
    lines         TEXT[] NOT NULL DEFAULT '{}',
    planned_start DATE, planned_end DATE, location TEXT,
    contact_name  TEXT, contact_role TEXT,                 -- colaborador responsable en la unidad
    manual_score  NUMERIC(5,2), manual_reason TEXT, manual_by UUID, manual_at TIMESTAMPTZ,
    pac_sent_at   TIMESTAMPTZ, pac_sent_to TEXT, pac_sent_by UUID,
    created_by    UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (manual_score IS NULL OR manual_score BETWEEN 0 AND 100),
    CHECK (planned_end IS NULL OR planned_start IS NULL OR planned_end >= planned_start)
);
CREATE INDEX ON engagement.audits (file_id);

CREATE TABLE engagement.team (
    audit_id UUID NOT NULL REFERENCES engagement.audits(id) ON DELETE CASCADE,
    user_id  UUID NOT NULL REFERENCES iam.users(id),
    role     VARCHAR(8) NOT NULL CHECK (role IN ('LIDER','AUDITOR')),
    initials VARCHAR(6) NOT NULL,                          -- solo iniciales de nombre y apellido
    PRIMARY KEY (audit_id, user_id)
);
CREATE UNIQUE INDEX one_leader_per_audit ON engagement.team (audit_id) WHERE role = 'LIDER';

-- 6. Fases: Planificación -> Trabajo de campo -> Informe
CREATE TABLE engagement.phase_log (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    from_phase VARCHAR(14), to_phase VARCHAR(14) NOT NULL,
    changed_by UUID NOT NULL, changed_at TIMESTAMPTZ NOT NULL DEFAULT now(), note TEXT
);

-- 4 y 5. Criterios por tipo de cédula y línea (editables por el Contralor)
CREATE TABLE engagement.templates (
    kind VARCHAR(12) NOT NULL CHECK (kind IN ('SUSCRIPCION','RECLAMO')),
    line VARCHAR(12) NOT NULL CHECK (line IN ('AUTO','PATRIMONIAL','PERSONAL')),
    version INT NOT NULL DEFAULT 1,
    criteria JSONB NOT NULL,
    updated_by UUID, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, line)
);

CREATE TABLE engagement.worksheets (
    id UUID PRIMARY KEY,
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    kind VARCHAR(12) NOT NULL CHECK (kind IN ('SUSCRIPCION','RECLAMO')),
    line VARCHAR(12) NOT NULL CHECK (line IN ('AUTO','PATRIMONIAL','PERSONAL')),
    title TEXT NOT NULL,
    criteria JSONB NOT NULL,                               -- copia de la plantilla al crear: la cédula no cambia después
    template_version INT NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','COMPLETED')),
    manual_score NUMERIC(5,2), manual_reason TEXT, manual_by UUID, manual_at TIMESTAMPTZ,
    created_by UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (audit_id, kind, line),
    CHECK (manual_score IS NULL OR manual_score BETWEEN 0 AND 100)
);

-- Cada fila de la cédula = una póliza o un siniestro de la muestra
CREATE TABLE engagement.items (
    id UUID PRIMARY KEY,
    worksheet_id UUID NOT NULL REFERENCES engagement.worksheets(id),
    ref VARCHAR(60) NOT NULL,
    results JSONB NOT NULL DEFAULT '{}',                   -- {código_criterio: CUMPLE|PARCIAL|NO_CUMPLE|NO_APLICA|EXCEPCION}
    auto_score NUMERIC(5,2),
    manual_score NUMERIC(5,2), manual_reason TEXT, manual_by UUID, manual_at TIMESTAMPTZ,
    observation TEXT,
    info_exception TEXT,                                   -- 3. observación de excepción por recepción de información
    source VARCHAR(8) NOT NULL DEFAULT 'ONLINE' CHECK (source IN ('ONLINE','OFFLINE')),
    updated_by UUID, updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (worksheet_id, ref),
    CHECK (manual_score IS NULL OR manual_score BETWEEN 0 AND 100)
);

CREATE TABLE engagement.observations (
    id UUID PRIMARY KEY,
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    item_id UUID REFERENCES engagement.items(id),
    seq INT NOT NULL,
    title TEXT NOT NULL, condition TEXT NOT NULL, criteria TEXT, cause TEXT, effect TEXT, recommendation TEXT,
    risk VARCHAR(5) NOT NULL CHECK (risk IN ('ALTO','MEDIO','BAJO')),
    unit_decision VARCHAR(10) CHECK (unit_decision IN ('ACEPTA','NO_ACEPTA','PARCIAL')),
    unit_response TEXT, unit_response_at DATE,
    pac_action TEXT, pac_owner TEXT, pac_due DATE,
    pac_status VARCHAR(10) NOT NULL DEFAULT 'PENDIENTE' CHECK (pac_status IN ('PENDIENTE','EN_CURSO','CUMPLIDA')),
    created_by UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (audit_id, seq)
);

-- 7.4 Anexo de evidencias (solo inserción: no se borran ni se sobrescriben)
CREATE TABLE engagement.evidence (
    id UUID PRIMARY KEY,
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    item_id UUID REFERENCES engagement.items(id),
    observation_id UUID REFERENCES engagement.observations(id),
    filename TEXT NOT NULL, content_type TEXT NOT NULL, size_bytes BIGINT NOT NULL,
    sha256 CHAR(64) NOT NULL, object_key TEXT NOT NULL, description TEXT,
    uploaded_by UUID NOT NULL, uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON engagement.evidence (audit_id);

-- 7.3 y 7.5 Informes: previo (hacia la unidad) y final (Auditor -> Contralor -> firmas)
CREATE TABLE engagement.reports (
    id UUID PRIMARY KEY,
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    kind VARCHAR(6) NOT NULL CHECK (kind IN ('PREVIO','FINAL')),
    version INT NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT','SENT','IN_REVIEW','RETURNED','APPROVED','SIGNED')),
    body JSONB NOT NULL, body_sha256 CHAR(64) NOT NULL,
    created_by UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at TIMESTAMPTZ,
    approved_by UUID, approved_at TIMESTAMPTZ, approved_body_sha256 CHAR(64),
    sent_to TEXT, sent_at TIMESTAMPTZ, sent_by UUID,
    UNIQUE (audit_id, kind, version),
    CHECK (approved_by IS NULL OR approved_by <> created_by)       -- doble control
);

-- Conversación Auditor <-> Contralor durante la revisión
CREATE TABLE engagement.report_comments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES engagement.reports(id),
    author UUID NOT NULL, kind VARCHAR(10) NOT NULL CHECK (kind IN ('REVISION','RESPUESTA','DEVOLUCION')),
    text TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7.6: iniciales de los auditores y datos del colaborador (la firma manuscrita va en la impresión)
CREATE TABLE engagement.signoffs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES engagement.reports(id),
    signer_type VARCHAR(18) NOT NULL CHECK (signer_type IN ('AUDITOR_INICIALES','COLABORADOR')),
    user_id UUID,                                          -- auditor; NULL para el colaborador
    display TEXT NOT NULL,                                 -- iniciales, o nombre y cargo del colaborador
    body_sha256 CHAR(64) NOT NULL, signed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    physical BOOLEAN NOT NULL DEFAULT FALSE, note TEXT,
    UNIQUE (report_id, signer_type, user_id)
);

-- 7.7: firmas electrónicas (PAdES) del Contralor y del Gerente de Control Interno. Solo inserción.
CREATE TABLE engagement.signed_documents (
    id UUID PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES engagement.reports(id),
    signer_role VARCHAR(10) NOT NULL CHECK (signer_role IN ('CONTRALOR','GERENTE_CI')),
    version INT NOT NULL,
    sha256_unsigned CHAR(64) NOT NULL, sha256_signed CHAR(64) NOT NULL, object_key TEXT NOT NULL,
    signer_user_id UUID NOT NULL, signer_subject TEXT NOT NULL, cert_serial TEXT NOT NULL, cert_sha256 CHAR(64) NOT NULL,
    signed_at TIMESTAMPTZ NOT NULL, tsa_url TEXT, timestamp_embedded BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (report_id, signer_role), UNIQUE (report_id, version)
);

CREATE OR REPLACE FUNCTION engagement.fn_append_only() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION '% es de solo inserción', TG_TABLE_NAME; END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_signed_append_only BEFORE UPDATE OR DELETE ON engagement.signed_documents FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();
CREATE TRIGGER trg_evidence_append_only BEFORE UPDATE OR DELETE ON engagement.evidence FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();
CREATE TRIGGER trg_signoffs_append_only BEFORE UPDATE OR DELETE ON engagement.signoffs FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();
CREATE TRIGGER trg_comments_append_only BEFORE UPDATE OR DELETE ON engagement.report_comments FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();

-- Privilegios mínimos
GRANT USAGE ON SCHEMA engagement TO app_rw;
GRANT SELECT, INSERT, UPDATE ON engagement.units, engagement.files, engagement.audits, engagement.templates, engagement.worksheets,
      engagement.items, engagement.observations, engagement.reports TO app_rw;
GRANT SELECT, INSERT ON engagement.team, engagement.phase_log, engagement.evidence, engagement.report_comments,
      engagement.signoffs, engagement.signed_documents TO app_rw;
GRANT DELETE ON engagement.team TO app_rw;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA engagement TO app_rw;
