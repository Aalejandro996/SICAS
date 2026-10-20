-- SICAS - Migración 019: separar los roles de Sistemas del motor analítico
-- de seguros. Conserva los permisos propios de auditoría ERP/TI.
BEGIN;

DELETE FROM iam.role_permissions rp
USING iam.roles r, iam.permissions p
WHERE rp.role_id = r.id
  AND rp.permission_id = p.id
  AND r.code IN ('AUDITOR_SISTEMAS', 'JEFE_AUDITORIA_SISTEMAS')
  AND p.code IN (
      'ingestion:upload',
      'ingestion:read',
      'ingestion:review_rejects',
      'ingestion:cancel',
      'rule:read',
      'rule:execute',
      'finding:read',
      'finding:triage',
      'finding:escalate'
  );

COMMIT;
