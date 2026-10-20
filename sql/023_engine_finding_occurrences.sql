-- SICAS - Migración 023:
-- Historial de detecciones por ejecución sin duplicar el hallazgo principal.
BEGIN;

CREATE TABLE IF NOT EXISTS engine.finding_occurrences (
    run_id UUID NOT NULL REFERENCES engine.runs(id) ON DELETE CASCADE,
    finding_id BIGINT NOT NULL REFERENCES engine.findings(id) ON DELETE CASCADE,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity VARCHAR(8) NOT NULL
        CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    score NUMERIC(6,2) NOT NULL,
    message TEXT NOT NULL,
    evidence JSONB NOT NULL,
    is_new BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (run_id, finding_id)
);

-- Backfill histórico: cada hallazgo ya existente cuenta como
-- primera detección en su ejecución original.
INSERT INTO engine.finding_occurrences
    (run_id, finding_id, detected_at, severity, score, message, evidence, is_new)
SELECT
    f.run_id, f.id, f.created_at, f.severity, f.score,
    f.message, f.evidence, TRUE
FROM engine.findings f
ON CONFLICT (run_id, finding_id) DO NOTHING;

COMMENT ON COLUMN engine.finding_occurrences.is_new IS
    'Primera detección o reapertura tras CLOSED_RESOLVED; el backfill histórico registra la detección original.';

CREATE INDEX IF NOT EXISTS idx_finding_occurrences_finding_detected
    ON engine.finding_occurrences (finding_id, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_finding_occurrences_run_severity
    ON engine.finding_occurrences (run_id, severity);

GRANT SELECT, INSERT ON engine.finding_occurrences TO app_rw;

COMMIT;
