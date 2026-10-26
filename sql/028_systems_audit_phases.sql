-- 028: fases propias de la Auditoría de Sistemas.
--   1. LEVANTAMIENTO  (levantamiento de información con la cédula y observaciones automáticas)
--   2. DOCUMENTACION  (solicitud y verificación de la documentación existente)
--   3. PRUEBAS_CAMPO  (pruebas sobre los controles documentados)
--   4. INFORME        (nota final = promedio de las notas de las fases 1, 2 y 3)
-- Las auditorías financieras y generales conservan PLANIFICACION / TRABAJO_CAMPO / INFORME.

ALTER TABLE engagement.audits DROP CONSTRAINT IF EXISTS audits_phase_check;
ALTER TABLE engagement.audits ADD CONSTRAINT audits_phase_check CHECK (phase IN (
    'PLANIFICACION', 'TRABAJO_CAMPO', 'INFORME', 'LEVANTAMIENTO', 'DOCUMENTACION', 'PRUEBAS_CAMPO'));

ALTER TABLE engagement.phase_score_snapshots DROP CONSTRAINT IF EXISTS phase_score_snapshots_phase_check;
ALTER TABLE engagement.phase_score_snapshots ADD CONSTRAINT phase_score_snapshots_phase_check CHECK (phase IN (
    'PLANIFICACION', 'TRABAJO_CAMPO', 'INFORME', 'LEVANTAMIENTO', 'DOCUMENTACION', 'PRUEBAS_CAMPO'));

-- Respuestas de cada control al cerrar cada fase: {"LEVANTAMIENTO": {...}, "DOCUMENTACION": {...}, ...}.
-- Permiten aplicar las reglas de la fase siguiente (control fijo en Documentación; en Pruebas de
-- campo solo los controles documentados).
ALTER TABLE engagement.items ADD COLUMN IF NOT EXISTS phase_results JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Observaciones redactadas por el motor de reglas al cargar la cédula (el auditor puede editarlas).
ALTER TABLE engagement.observations ADD COLUMN IF NOT EXISTS origin VARCHAR(10) NOT NULL DEFAULT 'MANUAL';
ALTER TABLE engagement.observations DROP CONSTRAINT IF EXISTS observations_origin_check;
ALTER TABLE engagement.observations ADD CONSTRAINT observations_origin_check CHECK (origin IN ('MANUAL', 'AUTO'));

-- Nota oficial de cada fase cerrada. Si una fase se reabre y se vuelve a cerrar, la nota se
-- actualiza; cada cierre queda además en phase_score_snapshots y en change_events.
CREATE TABLE IF NOT EXISTS engagement.audit_phase_scores (
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    phase VARCHAR(14) NOT NULL CHECK (phase IN ('LEVANTAMIENTO', 'DOCUMENTACION', 'PRUEBAS_CAMPO')),
    score NUMERIC(5, 2) CHECK (score IS NULL OR score BETWEEN 0 AND 100),
    rating VARCHAR(20) NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    closed_by UUID NOT NULL,
    closed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (audit_id, phase)
);
GRANT SELECT, INSERT, UPDATE ON engagement.audit_phase_scores TO app_rw;

-- Auditorías de Sistemas existentes: el cuestionario ya respondido corresponde al Levantamiento.
-- Solo cambia la fase vigente; el cambio queda en el historial de fases.
INSERT INTO engagement.phase_log (audit_id, from_phase, to_phase, changed_by, note)
SELECT a.id, a.phase, 'LEVANTAMIENTO', a.created_by, 'Adopción de las fases de Auditoría de Sistemas'
FROM engagement.audits a
WHERE a.audit_domain = 'SISTEMAS' AND a.phase IN ('PLANIFICACION', 'TRABAJO_CAMPO');

UPDATE engagement.audits SET phase = 'LEVANTAMIENTO'
WHERE audit_domain = 'SISTEMAS' AND phase IN ('PLANIFICACION', 'TRABAJO_CAMPO');
