-- SICAS - Migración 021:
-- Completar asignaciones declaradas en app/core/security/permissions.py
-- que no estaban presentes en la base existente.
-- No restablece permisos de ingesta/motor para roles de Sistemas.

BEGIN;

INSERT INTO iam.permissions (code, module, description)
VALUES (
    'audit:general_read',
    'engagement',
    'Acceso a auditorías generales existentes'
)
ON CONFLICT (code) DO NOTHING;

INSERT INTO iam.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM (
    VALUES
        ('AUDITOR', 'audit:general_read'),

        ('JEFE_AUDITORIA_FINANCIERA', 'audit:financial_manage'),
        ('JEFE_AUDITORIA_FINANCIERA', 'audit:initial'),
        ('JEFE_AUDITORIA_FINANCIERA', 'audit:manage'),
        ('JEFE_AUDITORIA_FINANCIERA', 'audit:pac_send'),
        ('JEFE_AUDITORIA_FINANCIERA', 'audit:rate'),
        ('JEFE_AUDITORIA_FINANCIERA', 'audit:report_draft'),
        ('JEFE_AUDITORIA_FINANCIERA', 'audit:report_submit'),
        ('JEFE_AUDITORIA_FINANCIERA', 'report:draft'),
        ('JEFE_AUDITORIA_FINANCIERA', 'report:submit'),

        ('JEFE_AUDITORIA_SISTEMAS', 'audit:initial'),
        ('JEFE_AUDITORIA_SISTEMAS', 'audit:manage'),
        ('JEFE_AUDITORIA_SISTEMAS', 'audit:pac_send'),
        ('JEFE_AUDITORIA_SISTEMAS', 'audit:rate'),
        ('JEFE_AUDITORIA_SISTEMAS', 'audit:report_draft'),
        ('JEFE_AUDITORIA_SISTEMAS', 'audit:report_submit'),
        ('JEFE_AUDITORIA_SISTEMAS', 'audit:systems_manage'),
        ('JEFE_AUDITORIA_SISTEMAS', 'report:draft'),
        ('JEFE_AUDITORIA_SISTEMAS', 'report:submit')
) AS desired(role_code, permission_code)
JOIN iam.roles r ON r.code = desired.role_code
JOIN iam.permissions p ON p.code = desired.permission_code
ON CONFLICT DO NOTHING;

COMMIT;
