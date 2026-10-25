-- 025: historial inmutable de transiciones del informe.
-- Cada cambio de estado (envío, devolución, aprobación, firma) inserta una fila
-- en la misma transacción que actualiza engagement.reports. La aprobación que una
-- devolución invalida en reports sigue constando aquí.

CREATE TABLE engagement.report_transitions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_id UUID NOT NULL REFERENCES engagement.reports(id),
    report_version INTEGER NOT NULL CHECK (report_version > 0),
    action VARCHAR(32) NOT NULL
        CHECK (action IN (
            'SUBMIT',
            'SEND_PREVIO',
            'RETURN',
            'APPROVE_JEFE',
            'APPROVE_SIGN_GERENTE',
            'APPROVE_SIGN_CONTRALOR'
        )),
    from_status VARCHAR(20) NOT NULL,
    to_status VARCHAR(20) NOT NULL,
    body_sha256 CHAR(64) NOT NULL,
    actor_id UUID NOT NULL,
    actor_username VARCHAR(80),
    actor_roles TEXT[] NOT NULL DEFAULT '{}',
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (from_status <> to_status),
    CHECK (action <> 'RETURN' OR length(btrim(coalesce(comment, ''))) >= 10)
);

CREATE INDEX report_transitions_report_idx
    ON engagement.report_transitions (report_id, id);

CREATE TRIGGER trg_report_transitions_append_only
    BEFORE UPDATE OR DELETE ON engagement.report_transitions
    FOR EACH ROW EXECUTE FUNCTION engagement.fn_append_only();

GRANT SELECT, INSERT ON engagement.report_transitions TO app_rw;
GRANT USAGE, SELECT ON SEQUENCE engagement.report_transitions_id_seq TO app_rw;
