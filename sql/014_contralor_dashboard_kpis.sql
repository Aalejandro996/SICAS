-- SICAS - Migración 014: dashboard privado del Contralor y KPI configurables.
-- Aditiva e idempotente. NO modifica auditorías, cédulas, informes ni sus estados.
-- Esta migración se revisa primero; no ejecutarla hasta autorizarlo expresamente.
BEGIN;

CREATE SCHEMA IF NOT EXISTS analytics;
GRANT USAGE ON SCHEMA analytics TO app_rw;

CREATE TABLE IF NOT EXISTS analytics.kpi_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(120) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    metric_code VARCHAR(40) NOT NULL CHECK (metric_code IN (
        'AUDITS_TOTAL', 'AUDITS_IN_PROGRESS', 'AUDITS_CLOSED', 'AUDIT_COMPLETION_PCT',
        'OBSERVATIONS_TOTAL', 'HIGH_RISK_OBSERVATIONS', 'HIGH_RISK_SHARE_PCT',
        'AVG_CLOSED_AUDIT_DAYS', 'AVG_PHASE_HOURS', 'INGESTION_AVG_SECONDS',
        'INGESTION_REJECTION_PCT'
    )),
    target_value NUMERIC(14,4) NOT NULL,
    warning_value NUMERIC(14,4),
    direction VARCHAR(12) NOT NULL CHECK (direction IN ('AT_LEAST', 'AT_MOST')),
    periodicity VARCHAR(12) NOT NULL CHECK (periodicity IN ('MENSUAL', 'TRIMESTRAL', 'SEMESTRAL', 'ANUAL')),
    scope_type VARCHAR(12) NOT NULL CHECK (scope_type IN ('GENERAL', 'UNIDAD', 'AUDITOR')),
    unit_id INTEGER REFERENCES engagement.units(id) ON DELETE RESTRICT,
    auditor_id UUID REFERENCES iam.users(id) ON DELETE RESTRICT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NOT NULL REFERENCES iam.users(id) ON DELETE RESTRICT,
    updated_by UUID NOT NULL REFERENCES iam.users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
      (scope_type = 'GENERAL' AND unit_id IS NULL AND auditor_id IS NULL) OR
      (scope_type = 'UNIDAD' AND unit_id IS NOT NULL AND auditor_id IS NULL) OR
      (scope_type = 'AUDITOR' AND unit_id IS NULL AND auditor_id IS NOT NULL)
    ),
    CHECK (
      warning_value IS NULL OR
      (direction = 'AT_LEAST' AND warning_value <= target_value) OR
      (direction = 'AT_MOST' AND warning_value >= target_value)
    )
);

CREATE INDEX IF NOT EXISTS idx_kpi_definitions_active_period
    ON analytics.kpi_definitions(active, periodicity);
CREATE INDEX IF NOT EXISTS idx_kpi_definitions_unit
    ON analytics.kpi_definitions(unit_id) WHERE unit_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_kpi_definitions_auditor
    ON analytics.kpi_definitions(auditor_id) WHERE auditor_id IS NOT NULL;

-- Permisos nuevos y exclusivos del rol CONTRALOR. No se retiran los permisos actuales de GERENCIA.
INSERT INTO iam.permissions(code, module, description) VALUES
  ('dashboard:contralor', 'analytics', 'Acceso exclusivo al dashboard agregado de Contraloría'),
  ('kpi:manage', 'analytics', 'Crear, modificar y desactivar KPI del dashboard de Contraloría')
ON CONFLICT (code) DO UPDATE
  SET module = EXCLUDED.module, description = EXCLUDED.description;

INSERT INTO iam.role_permissions(role_id, permission_id)
SELECT r.id, p.id
FROM iam.roles r CROSS JOIN iam.permissions p
WHERE r.code = 'CONTRALOR'
  AND p.code IN ('dashboard:contralor', 'kpi:manage')
ON CONFLICT DO NOTHING;

GRANT SELECT, INSERT, UPDATE ON analytics.kpi_definitions TO app_rw;
COMMIT;
