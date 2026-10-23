-- 024: instantáneas históricas e inmutables de puntuación por fase.
-- La captura de la instantánea se confirma en la misma transacción que
-- el cambio de fase, el envío del informe final o el cierre por PAC.

CREATE TABLE engagement.phase_score_snapshots (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    phase_log_id BIGINT REFERENCES engagement.phase_log(id),
    report_id UUID REFERENCES engagement.reports(id),
    report_version INTEGER CHECK (report_version IS NULL OR report_version > 0),
    phase VARCHAR(14) NOT NULL
        CHECK (phase IN ('PLANIFICACION', 'TRABAJO_CAMPO', 'INFORME')),
    trigger_action VARCHAR(32) NOT NULL
        CHECK (trigger_action IN (
            'PHASE_CHANGE',
            'FINAL_REPORT_SUBMITTED',
            'PAC_SENT'
        )),
    captured_by UUID NOT NULL,
    captured_username VARCHAR(80),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    scorecard JSONB NOT NULL
);

CREATE INDEX phase_score_snapshots_audit_time_idx
    ON engagement.phase_score_snapshots (audit_id, captured_at, id);

CREATE INDEX phase_score_snapshots_phase_idx
    ON engagement.phase_score_snapshots (audit_id, phase, captured_at);

CREATE TRIGGER trg_phase_score_snapshots_append_only
    BEFORE UPDATE OR DELETE ON engagement.phase_score_snapshots
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();

GRANT SELECT, INSERT ON engagement.phase_score_snapshots TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE engagement.phase_score_snapshots_id_seq TO app_rw;
