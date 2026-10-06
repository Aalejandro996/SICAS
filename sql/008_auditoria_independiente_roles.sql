-- Roles y segregación de auditoría financiera / sistemas. Idempotente para instalaciones existentes.
BEGIN;
ALTER TABLE engagement.files ADD COLUMN IF NOT EXISTS audit_domain VARCHAR(12) NOT NULL DEFAULT 'GENERAL';
ALTER TABLE engagement.audits ADD COLUMN IF NOT EXISTS audit_domain VARCHAR(12) NOT NULL DEFAULT 'GENERAL';
ALTER TABLE engagement.files DROP CONSTRAINT IF EXISTS files_audit_domain_check;
ALTER TABLE engagement.audits DROP CONSTRAINT IF EXISTS audits_audit_domain_check;
ALTER TABLE engagement.files ADD CONSTRAINT files_audit_domain_check CHECK (audit_domain IN ('GENERAL','FINANCIERA','SISTEMAS'));
ALTER TABLE engagement.audits ADD CONSTRAINT audits_audit_domain_check CHECK (audit_domain IN ('GENERAL','FINANCIERA','SISTEMAS'));
CREATE INDEX IF NOT EXISTS idx_engagement_files_domain ON engagement.files(audit_domain);
CREATE INDEX IF NOT EXISTS idx_engagement_audits_domain ON engagement.audits(audit_domain);
COMMIT;
