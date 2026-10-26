-- 026: trazabilidad del módulo de auditoría.
--   report_body_revisions : cada contenido generado del informe (la regeneración ya no pierde el anterior).
--   change_events         : bitácora de cambios por expediente, escrita en la misma transacción que el cambio.
--   observation_revisions : versiones de cada observación con motivo de la modificación.
--   review_points         : puntos a corregir que acompañan una devolución (pendiente / atendido).
--   report_reopenings     : autorización de Contraloría para emitir una nueva versión tras la firma.
-- Todas son de solo inserción salvo la atención de review_points, restringida por trigger.

CREATE TABLE engagement.report_body_revisions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES engagement.reports(id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    body JSONB NOT NULL,
    body_sha256 CHAR(64) NOT NULL,
    reason TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (report_id, revision)
);
CREATE INDEX report_body_revisions_sha_idx ON engagement.report_body_revisions (report_id, body_sha256);

CREATE TABLE engagement.change_events (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    audit_id UUID NOT NULL REFERENCES engagement.audits(id),
    report_id UUID REFERENCES engagement.reports(id),
    entity_type VARCHAR(32) NOT NULL,
    entity_id TEXT,
    action VARCHAR(48) NOT NULL,
    changes JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    audit_phase VARCHAR(14),
    report_status VARCHAR(20),
    actor_id UUID NOT NULL,
    actor_username VARCHAR(80),
    actor_roles TEXT[] NOT NULL DEFAULT '{}',
    request_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX change_events_audit_idx ON engagement.change_events (audit_id, id);
CREATE INDEX change_events_entity_idx ON engagement.change_events (entity_type, entity_id);

CREATE TABLE engagement.observation_revisions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    observation_id UUID NOT NULL REFERENCES engagement.observations(id),
    revision INTEGER NOT NULL CHECK (revision > 0),
    data JSONB NOT NULL,
    changed_fields TEXT[] NOT NULL DEFAULT '{}',
    reason TEXT,
    report_status VARCHAR(20),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (observation_id, revision),
    CHECK (revision = 1 OR length(btrim(coalesce(reason, ''))) >= 10)
);

CREATE TABLE engagement.review_points (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES engagement.reports(id),
    transition_id BIGINT NOT NULL REFERENCES engagement.report_transitions(id),
    target_type VARCHAR(12) NOT NULL CHECK (target_type IN ('GENERAL', 'OBSERVATION', 'ITEM', 'WORKSHEET')),
    target_id TEXT,
    target_label TEXT,
    description TEXT NOT NULL CHECK (length(btrim(description)) >= 5),
    status VARCHAR(10) NOT NULL DEFAULT 'PENDIENTE' CHECK (status IN ('PENDIENTE', 'ATENDIDO')),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    attended_by UUID,
    attended_at TIMESTAMPTZ,
    attended_note TEXT,
    CHECK (target_type = 'GENERAL' OR target_id IS NOT NULL),
    CHECK (status = 'PENDIENTE' OR (attended_by IS NOT NULL AND attended_at IS NOT NULL
                                    AND length(btrim(coalesce(attended_note, ''))) >= 10))
);
CREATE INDEX review_points_report_idx ON engagement.review_points (report_id, status);

-- Un punto solo puede pasar una vez de PENDIENTE a ATENDIDO; el resto de la fila no cambia.
CREATE OR REPLACE FUNCTION engagement.fn_review_point_attend_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'review_points no admite borrado';
    END IF;
    IF OLD.status <> 'PENDIENTE' OR NEW.status <> 'ATENDIDO'
       OR NEW.report_id IS DISTINCT FROM OLD.report_id
       OR NEW.transition_id IS DISTINCT FROM OLD.transition_id
       OR NEW.target_type IS DISTINCT FROM OLD.target_type
       OR NEW.target_id IS DISTINCT FROM OLD.target_id
       OR NEW.target_label IS DISTINCT FROM OLD.target_label
       OR NEW.description IS DISTINCT FROM OLD.description
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'review_points: solo se permite marcar como ATENDIDO un punto pendiente';
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_review_points_attend_only
    BEFORE UPDATE OR DELETE ON engagement.review_points
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_review_point_attend_only();

CREATE TABLE engagement.report_reopenings (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL UNIQUE REFERENCES engagement.reports(id),
    reason TEXT NOT NULL CHECK (length(btrim(reason)) >= 20),
    authorized_by UUID NOT NULL,
    authorized_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TRIGGER trg_report_body_revisions_append_only
    BEFORE UPDATE OR DELETE ON engagement.report_body_revisions
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();
CREATE TRIGGER trg_change_events_append_only
    BEFORE UPDATE OR DELETE ON engagement.change_events
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();
CREATE TRIGGER trg_observation_revisions_append_only
    BEFORE UPDATE OR DELETE ON engagement.observation_revisions
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();
CREATE TRIGGER trg_report_reopenings_append_only
    BEFORE UPDATE OR DELETE ON engagement.report_reopenings
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();

-- Iniciales: la unicidad incluye el contenido firmado. Antes, tras regenerar el informe el
-- auditor no podía volver a estampar sus iniciales (ON CONFLICT descartaba la nueva) y el
-- informe devuelto no podía reenviarse. Las iniciales anteriores se conservan.
DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'engagement.signoffs'::regclass AND contype = 'u'
      AND pg_get_constraintdef(oid) = 'UNIQUE (report_id, signer_type, user_id)'
  LOOP
    EXECUTE format('ALTER TABLE engagement.signoffs DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
ALTER TABLE engagement.signoffs
    ADD CONSTRAINT signoffs_report_signer_user_body_key UNIQUE (report_id, signer_type, user_id, body_sha256);

-- Línea base: el contenido vigente de cada informe y de cada observación pasa a ser
-- su revisión 1. Solo se insertan filas; no se modifica ningún dato existente.
INSERT INTO engagement.report_body_revisions (report_id, revision, body, body_sha256, reason, created_by, created_at)
SELECT r.id, 1, r.body, r.body_sha256, 'Contenido vigente al activar el historial de revisiones', r.created_by, r.updated_at
FROM engagement.reports r;

INSERT INTO engagement.observation_revisions (observation_id, revision, data, reason, created_by, created_at)
SELECT o.id, 1,
       to_jsonb(o) - 'id' - 'audit_id' - 'seq' - 'created_by' - 'created_at' - 'updated_at',
       'Contenido vigente al activar el historial de revisiones', o.created_by, o.updated_at
FROM engagement.observations o;

GRANT SELECT, INSERT ON engagement.report_body_revisions, engagement.change_events,
      engagement.observation_revisions, engagement.report_reopenings TO app_rw;
GRANT SELECT, INSERT, UPDATE ON engagement.review_points TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE engagement.report_body_revisions_id_seq, engagement.change_events_id_seq,
      engagement.observation_revisions_id_seq, engagement.review_points_id_seq,
      engagement.report_reopenings_id_seq TO app_rw;
