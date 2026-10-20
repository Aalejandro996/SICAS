-- SICAS - Migración 020:
-- Restablecer las asignaciones de ingesta y motor declaradas
-- en app/core/security/permissions.py para los roles financieros.
-- No altera otros roles ni permisos de auditoría ERP/TI.
BEGIN;

INSERT INTO iam.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM iam.roles r
JOIN iam.permissions p ON (
    (r.code = 'AUDITOR_FINANCIERO' AND p.code IN (
        'ingestion:upload',
        'ingestion:read',
        'ingestion:review_rejects',
        'ingestion:cancel',
        'rule:read',
        'rule:execute'
    ))
    OR
    (r.code = 'JEFE_AUDITORIA_FINANCIERA' AND p.code IN (
        'ingestion:read',
        'ingestion:review_rejects',
        'rule:read',
        'rule:execute'
    ))
)
ON CONFLICT DO NOTHING;

COMMIT;
