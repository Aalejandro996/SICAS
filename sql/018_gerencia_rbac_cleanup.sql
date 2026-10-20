-- SICAS - Migración 018: alinear permisos persistidos de GERENCIA
-- con la matriz RBAC definida en app/core/security/permissions.py.
-- Solo elimina asociaciones obsoletas de este rol.
BEGIN;

DELETE FROM iam.role_permissions rp
USING iam.roles r, iam.permissions p
WHERE rp.role_id = r.id
  AND rp.permission_id = p.id
  AND r.code = 'GERENCIA'
  AND p.code IN ('audit:read', 'kpi:export');

COMMIT;
