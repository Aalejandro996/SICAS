-- SICAS - Migración 016: registro explícito de actividad de auditores.
-- Aditiva. No cambia ni altera auditorías, cédulas, observaciones o informes existentes.
BEGIN;

CREATE TABLE IF NOT EXISTS analytics.auditor_activity_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_id UUID NOT NULL REFERENCES engagement.audits(id) ON DELETE RESTRICT,
    user_id UUID NOT NULL REFERENCES iam.users(id) ON DELETE RESTRICT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_resumed_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    status VARCHAR(12) NOT NULL CHECK (status IN ('RUNNING','PAUSED','STOPPED')),
    accumulated_seconds BIGINT NOT NULL DEFAULT 0 CHECK (accumulated_seconds >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ended_at IS NULL OR ended_at >= started_at),
    CHECK (last_resumed_at IS NULL OR last_resumed_at >= started_at),
    CHECK (
      (status='RUNNING' AND last_resumed_at IS NOT NULL AND ended_at IS NULL) OR
      (status='PAUSED' AND last_resumed_at IS NULL AND ended_at IS NULL) OR
      (status='STOPPED' AND last_resumed_at IS NULL AND ended_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_auditor_activity_one_open_session
    ON analytics.auditor_activity_sessions(user_id)
    WHERE status IN ('RUNNING','PAUSED');
CREATE INDEX IF NOT EXISTS idx_auditor_activity_user_started
    ON analytics.auditor_activity_sessions(user_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_auditor_activity_audit_started
    ON analytics.auditor_activity_sessions(audit_id, started_at DESC);

CREATE OR REPLACE FUNCTION analytics.guard_auditor_activity_session()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'El historial de actividad no se puede borrar';
    END IF;
    IF OLD.status = 'STOPPED' THEN
        RAISE EXCEPTION 'Las sesiones finalizadas son inmutables';
    END IF;
    IF NEW.audit_id <> OLD.audit_id OR NEW.user_id <> OLD.user_id OR NEW.started_at <> OLD.started_at THEN
        RAISE EXCEPTION 'La identidad de una sesión no se puede cambiar';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_guard_auditor_activity_session ON analytics.auditor_activity_sessions;
CREATE TRIGGER trg_guard_auditor_activity_session
BEFORE UPDATE OR DELETE ON analytics.auditor_activity_sessions
FOR EACH ROW EXECUTE FUNCTION analytics.guard_auditor_activity_session();

GRANT USAGE ON SCHEMA analytics TO app_rw;
GRANT SELECT, INSERT, UPDATE ON analytics.auditor_activity_sessions TO app_rw;
COMMIT;
