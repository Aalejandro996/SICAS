-- 033: herramientas del Administrador del Sistema.
--  - Anulación de auditorías creadas por error con doble control (propone el Administrador, aprueba el Contralor).
--  - Latido de los servicios en segundo plano (worker y beat) para el monitor.
--  - Revisiones periódicas de accesos (evidencia).
--  - Verificación de restauración de respaldos con doble control.
--  - Catálogos de codificación institucional en base de datos y cambios de unidades y codificación con doble control.

CREATE TABLE engagement.audit_annulment_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id      UUID NOT NULL REFERENCES engagement.audits(id),
    audit_code    VARCHAR(30) NOT NULL,
    reason        TEXT NOT NULL CHECK (length(btrim(reason)) >= 15),
    requested_by  UUID NOT NULL REFERENCES iam.users(id),
    status        VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    decided_by    UUID REFERENCES iam.users(id),
    decided_at    TIMESTAMPTZ,
    decision_note TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decided_by IS NULL OR decided_by <> requested_by)
);
CREATE UNIQUE INDEX audit_annulment_one_pending ON engagement.audit_annulment_requests (audit_id) WHERE status = 'PENDING';
GRANT SELECT, INSERT, UPDATE ON engagement.audit_annulment_requests TO app_rw;

CREATE TABLE admin.service_heartbeats (
    service    VARCHAR(30) PRIMARY KEY,
    last_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail     JSONB NOT NULL DEFAULT '{}'::jsonb
);
GRANT SELECT, INSERT, UPDATE ON admin.service_heartbeats TO app_rw;

CREATE TABLE admin.access_reviews (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    performed_by UUID NOT NULL REFERENCES iam.users(id),
    performed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    inactive_days INT NOT NULL,
    summary      JSONB NOT NULL,
    note         TEXT
);
CREATE TRIGGER trg_access_reviews_append_only BEFORE UPDATE OR DELETE ON admin.access_reviews
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();
GRANT SELECT, INSERT ON admin.access_reviews TO app_rw;

CREATE TABLE admin.restore_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    backup_id     UUID NOT NULL REFERENCES admin.backups(id),
    reason        TEXT NOT NULL CHECK (length(btrim(reason)) >= 15),
    requested_by  UUID NOT NULL REFERENCES iam.users(id),
    status        VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    decided_by    UUID REFERENCES iam.users(id),
    decided_at    TIMESTAMPTZ,
    decision_note TEXT,
    verify_status VARCHAR(10) CHECK (verify_status IN ('RUNNING','OK','FAILED')),
    verify_detail JSONB,
    verified_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decided_by IS NULL OR decided_by <> requested_by)
);
CREATE UNIQUE INDEX restore_one_pending ON admin.restore_requests (backup_id) WHERE status = 'PENDING';
GRANT SELECT, INSERT, UPDATE ON admin.restore_requests TO app_rw;

-- Catálogos de la codificación institucional (antes fijos en codification.py).
CREATE TABLE engagement.codification_catalog (
    catalog    VARCHAR(20) NOT NULL CHECK (catalog IN ('AUDIT_TYPE','COMPANY','PLAN_TYPE','PROCESS','FREQUENCY','REPORT_COMPANY')),
    code       VARCHAR(6) NOT NULL CHECK (code ~ '^[A-Z]{1,6}$'),
    label      TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 100,
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (catalog, code)
);
GRANT SELECT, INSERT, UPDATE ON engagement.codification_catalog TO app_rw;
INSERT INTO engagement.codification_catalog (catalog, code, label, sort_order) VALUES
    ('AUDIT_TYPE', 'P', 'Personas', 10),
    ('AUDIT_TYPE', 'A', 'Auditoría de Sucursal', 20),
    ('AUDIT_TYPE', 'C', 'Contraloría', 30),
    ('AUDIT_TYPE', 'S', 'Sistema', 40),
    ('AUDIT_TYPE', 'LC', 'Legitimación de Capitales', 50),
    ('COMPANY', 'SC', 'Seguros Constitución, C.A.', 10),
    ('COMPANY', 'ASN', 'Asistanet, C.A.', 20),
    ('COMPANY', 'CAR', 'Caravana de la Salud, C.A.', 30),
    ('COMPANY', 'BTM', 'Farmacias Botimarket, C.A.', 40),
    ('COMPANY', 'RPF', 'RPF, C.A.', 50),
    ('COMPANY', 'INSG', 'Financiadora de Primas Inversora Segucons, C.A.', 60),
    ('COMPANY', 'SGRK', 'Segurisk Corretaje de Seguros, C.A.', 70),
    ('COMPANY', 'VIDP', 'Vida y Patrimonio Corretaje de Seguros, C.A.', 80),
    ('COMPANY', 'AGC', 'Águila Corretaje de Seguros, C.A.', 90),
    ('COMPANY', 'VEN', 'Veneasesores Corretaje de Seguros, C.A.', 100),
    ('PLAN_TYPE', 'P', 'Planificada', 10),
    ('PLAN_TYPE', 'E', 'Especial', 20),
    ('PROCESS', 'O', 'Operativo', 10),
    ('PROCESS', 'T', 'Técnico', 20),
    ('PROCESS', 'A', 'Administrativo', 30),
    ('PROCESS', 'C', 'Comercial', 40),
    ('PROCESS', 'S', 'Sistema', 50),
    ('PROCESS', 'E', 'Especial', 60),
    ('PROCESS', 'F', 'Financiera', 70),
    ('PROCESS', 'LC', 'Legitimación de Capitales', 80),
    ('PROCESS', 'IS', 'Inversora Segucons', 90),
    ('PROCESS', 'CR', 'Compañías Relacionadas', 100),
    ('FREQUENCY', 'S', 'Seguimiento', 10),
    ('FREQUENCY', 'G', 'General', 20),
    ('FREQUENCY', 'E', 'Especial', 30),
    ('REPORT_COMPANY', 'SC', 'Seguros Constitución, C.A.', 10),
    ('REPORT_COMPANY', 'CR', 'Compañías del Grupo', 20)
ON CONFLICT DO NOTHING;

-- Cambios de unidades y de codificación por el mismo circuito de doble control que las reglas.
ALTER TABLE engagement.rule_change_requests DROP CONSTRAINT IF EXISTS rule_change_requests_engine_check;
ALTER TABLE engagement.rule_change_requests ALTER COLUMN engine TYPE VARCHAR(12);
ALTER TABLE engagement.rule_change_requests ADD CONSTRAINT rule_change_requests_engine_check
    CHECK (engine IN ('SUDEASEG','SISTEMAS','ANALITICO','UNIDAD','CODIFICACION'));

-- Acciones del Administrador del Sistema con doble verificación: MFA reciente al solicitar y
-- aprobación del Contralor (también con MFA) antes de ejecutarse.
CREATE TABLE admin.action_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action        VARCHAR(30) NOT NULL CHECK (action IN ('SECURITY_POLICY','REVOKE_SESSIONS','DEACTIVATE_USER','ACCESS_REVIEW','SMTP_TEST')),
    payload       JSONB NOT NULL,
    summary       TEXT NOT NULL,
    reason        TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
    requested_by  UUID NOT NULL REFERENCES iam.users(id),
    status        VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED','FAILED')),
    decided_by    UUID REFERENCES iam.users(id),
    decided_at    TIMESTAMPTZ,
    decision_note TEXT,
    result        JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decided_by IS NULL OR decided_by <> requested_by)
);
CREATE INDEX action_requests_pending ON admin.action_requests (created_at) WHERE status = 'PENDING';
GRANT SELECT, INSERT, UPDATE ON admin.action_requests TO app_rw;
