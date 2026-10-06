BEGIN;

-- Flujo nuevo: Auditor -> Jefe -> Gerencia -> Contralor.
-- Gerencia y Contralor pueden aprobar y firmar en una sola operación.

ALTER TABLE engagement.reports
    ALTER COLUMN status TYPE VARCHAR(20);

ALTER TABLE engagement.reports
    DROP CONSTRAINT IF EXISTS reports_status_check;

ALTER TABLE engagement.reports
    ADD CONSTRAINT reports_status_check
    CHECK (status IN ('DRAFT','SENT','IN_REVIEW','RETURNED','GERENCIA','CONTRALOR','APPROVED','SIGNED'));

ALTER TABLE engagement.reports
    ADD COLUMN IF NOT EXISTS jefe_approved_by UUID,
    ADD COLUMN IF NOT EXISTS jefe_approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS jefe_approved_body_sha256 CHAR(64),
    ADD COLUMN IF NOT EXISTS gerente_approved_by UUID,
    ADD COLUMN IF NOT EXISTS gerente_approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS gerente_approved_body_sha256 CHAR(64),
    ADD COLUMN IF NOT EXISTS contralor_approved_by UUID,
    ADD COLUMN IF NOT EXISTS contralor_approved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS contralor_approved_body_sha256 CHAR(64);

ALTER TABLE engagement.reports
    DROP CONSTRAINT IF EXISTS reports_jefe_not_creator,
    DROP CONSTRAINT IF EXISTS reports_gerente_not_creator,
    DROP CONSTRAINT IF EXISTS reports_contralor_not_creator;

ALTER TABLE engagement.reports
    ADD CONSTRAINT reports_jefe_not_creator
    CHECK (jefe_approved_by IS NULL OR jefe_approved_by <> created_by),
    ADD CONSTRAINT reports_gerente_not_creator
    CHECK (gerente_approved_by IS NULL OR gerente_approved_by <> created_by),
    ADD CONSTRAINT reports_contralor_not_creator
    CHECK (contralor_approved_by IS NULL OR contralor_approved_by <> created_by);

-- Permitir conservar el histórico de firmas cuando un informe es devuelto
-- después de la firma de Gerencia y posteriormente se regenera.
DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'engagement.signed_documents'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) LIKE '%report_id%signer_role%'
  LOOP
    EXECUTE format('ALTER TABLE engagement.signed_documents DROP CONSTRAINT IF EXISTS %I', c.conname);
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_signed_documents_report_role_version
    ON engagement.signed_documents(report_id, signer_role, version);

-- Permisos nuevos para la cadena de autorización.
INSERT INTO iam.permissions(code, module, description) VALUES
('audit:report_approve_jefe', 'engagement', 'Aprobar o devolver el informe final como Jefe de Auditoría'),
('audit:report_approve_gerente', 'engagement', 'Aprobar y devolver el informe final como Gerencia')
ON CONFLICT (code) DO UPDATE SET module = EXCLUDED.module, description = EXCLUDED.description;

INSERT INTO iam.role_permissions(role_id, permission_id)
SELECT r.id, p.id FROM iam.roles r, iam.permissions p
WHERE r.code IN ('JEFE_AUDITORIA_FINANCIERA','JEFE_AUDITORIA_SISTEMAS')
  AND p.code = 'audit:report_approve_jefe'
ON CONFLICT DO NOTHING;

INSERT INTO iam.role_permissions(role_id, permission_id)
SELECT r.id, p.id FROM iam.roles r, iam.permissions p
WHERE r.code = 'GERENCIA'
  AND p.code = 'audit:report_approve_gerente'
ON CONFLICT DO NOTHING;

-- La aprobación del Jefe/Gerencia es un control adicional y no modifica
-- los permisos existentes del Contralor.

COMMIT;
