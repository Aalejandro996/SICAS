-- SICAS - Migración 015: cortes históricos verificables del Dashboard del Contralor.
-- Aditiva: no altera auditorías, observaciones, cédulas, informes ni KPI existentes.
BEGIN;

CREATE TABLE IF NOT EXISTS analytics.dashboard_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
    source VARCHAR(12) NOT NULL CHECK (source IN ('MANUAL','AUTOMATICO')),
    captured_by UUID REFERENCES iam.users(id) ON DELETE RESTRICT,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dashboard_snapshots_date ON analytics.dashboard_snapshots(snapshot_date DESC, created_at DESC);

CREATE TABLE IF NOT EXISTS analytics.kpi_measurements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_id UUID NOT NULL REFERENCES analytics.dashboard_snapshots(id) ON DELETE RESTRICT,
    kpi_id UUID NOT NULL REFERENCES analytics.kpi_definitions(id) ON DELETE RESTRICT,
    metric_code VARCHAR(40) NOT NULL,
    actual_value NUMERIC(14,4),
    target_value NUMERIC(14,4) NOT NULL,
    warning_value NUMERIC(14,4),
    direction VARCHAR(12) NOT NULL CHECK (direction IN ('AT_LEAST','AT_MOST')),
    status_result VARCHAR(20) NOT NULL CHECK (status_result IN ('CUMPLIDO','ATENCION','DESVIACION','SIN_DATOS','INACTIVO')),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(snapshot_id, kpi_id),
    CHECK (period_end >= period_start)
);
CREATE INDEX IF NOT EXISTS idx_kpi_measurements_kpi_date ON analytics.kpi_measurements(kpi_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kpi_measurements_snapshot ON analytics.kpi_measurements(snapshot_id);

-- La aplicación puede consultar e insertar; no puede alterar ni borrar cortes existentes.
-- CREATE TABLE IF NOT EXISTS no restablece los privilegios de tablas preexistentes.
REVOKE ALL PRIVILEGES
    ON TABLE analytics.dashboard_snapshots, analytics.kpi_measurements
    FROM app_rw;

GRANT USAGE ON SCHEMA analytics TO app_rw;
GRANT SELECT, INSERT ON analytics.dashboard_snapshots TO app_rw;
GRANT SELECT, INSERT ON analytics.kpi_measurements TO app_rw;
COMMIT;
