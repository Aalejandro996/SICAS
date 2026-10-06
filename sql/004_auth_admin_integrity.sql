-- 004: Autenticación reforzada, doble control de roles, integridad del audit trail, lista restrictiva
ALTER TABLE iam.users
    ADD COLUMN lockouts      SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN mfa_last_step BIGINT,                      -- último paso TOTP aceptado (anti-repetición)
    ADD COLUMN id_blind_idx  CHAR(64);

ALTER TABLE iam.mfa_devices ADD CONSTRAINT mfa_one_per_user UNIQUE (user_id);

ALTER TABLE iam.refresh_tokens
    ADD COLUMN family_id UUID NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN used_at   TIMESTAMPTZ;
CREATE INDEX ON iam.refresh_tokens (family_id);
CREATE INDEX ON iam.refresh_tokens (user_id) WHERE revoked_at IS NULL;

CREATE TABLE iam.password_history (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON iam.password_history (user_id, created_at DESC);

-- Cambios de rol con doble control: solicitar (SYS_ADMIN) -> aprobar (Contralor, otra persona)
CREATE TABLE iam.role_change_requests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_user_id UUID NOT NULL REFERENCES iam.users(id),
    role_id        SMALLINT NOT NULL REFERENCES iam.roles(id),
    action         VARCHAR(6) NOT NULL CHECK (action IN ('GRANT','REVOKE')),
    reason         TEXT NOT NULL,
    requested_by   UUID NOT NULL REFERENCES iam.users(id),
    status         VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    decided_by     UUID REFERENCES iam.users(id),
    decided_at     TIMESTAMPTZ, decision_note TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (requested_by <> target_user_id),               -- nadie se asigna roles a sí mismo
    CHECK (decided_by IS NULL OR (decided_by <> requested_by AND decided_by <> target_user_id))
);
CREATE UNIQUE INDEX ON iam.role_change_requests (target_user_id, role_id, action) WHERE status = 'PENDING';

-- ===== Integridad del audit trail =====
-- Recalcula cada hash y verifica el encadenamiento. Devuelve las filas inconsistentes.
CREATE OR REPLACE FUNCTION audit.verify_chain(p_from BIGINT DEFAULT 0)
RETURNS TABLE (broken_id BIGINT, reason TEXT) LANGUAGE sql STABLE AS $$
    WITH o AS (
        SELECT id, prev_hash, row_hash,
               LAG(row_hash) OVER (ORDER BY id) AS expected_prev,
               audit.fn_row_digest(prev_hash, occurred_at, request_id, actor_id, action, entity_type,
                                   entity_id, outcome, before_data, after_data, metadata) AS recomputed
        FROM audit.audit_log WHERE id >= p_from)
    SELECT id, CASE WHEN row_hash <> recomputed THEN 'CONTENIDO_ALTERADO' ELSE 'ENCADENAMIENTO_ROTO' END
    FROM o
    WHERE row_hash <> recomputed
       OR (expected_prev IS NOT NULL AND prev_hash IS DISTINCT FROM expected_prev)
    ORDER BY id
$$;

-- Puntos de anclaje firmados (Ed25519): detectan también el borrado de las últimas filas
CREATE TABLE audit.chain_checkpoints (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL,
    last_audit_id BIGINT NOT NULL,
    last_hash     BYTEA  NOT NULL,
    key_id        TEXT   NOT NULL,
    signature     BYTEA  NOT NULL
);
CREATE TRIGGER trg_checkpoint_immutable BEFORE UPDATE OR DELETE ON audit.chain_checkpoints
    FOR EACH ROW EXECUTE FUNCTION audit.fn_block_mutation();
GRANT INSERT ON audit.chain_checkpoints TO app_rw;
GRANT SELECT ON audit.chain_checkpoints TO audit_reader, app_rw;
GRANT EXECUTE ON FUNCTION audit.verify_chain(BIGINT) TO audit_reader, app_rw;
-- verify_chain lee audit_log: la app necesita SELECT solo a través de esta función
ALTER FUNCTION audit.verify_chain(BIGINT) SECURITY DEFINER SET search_path = audit, public;

-- ===== Lista restrictiva LC/FT (cargada por el Oficial de Cumplimiento) =====
CREATE SCHEMA IF NOT EXISTS compliance;
CREATE TABLE compliance.watchlist (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    list_name    VARCHAR(60) NOT NULL,
    doc_id_norm  VARCHAR(30) NOT NULL,                    -- identificador normalizado (V12345678)
    full_name    TEXT,
    added_by     UUID NOT NULL, added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    active       BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX ON compliance.watchlist (doc_id_norm) WHERE active;

-- ===== Particiones mensuales del audit trail (la app no tiene permisos DDL: función SECURITY DEFINER) =====
CREATE OR REPLACE FUNCTION audit.ensure_partitions(p_months_ahead INT DEFAULT 3) RETURNS INT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = audit, public AS $$
DECLARE m DATE; n INT := 0; part TEXT;
BEGIN
    FOR i IN 0..p_months_ahead LOOP
        m := (date_trunc('month', now()) + make_interval(months => i))::date;
        part := format('audit_log_%s', to_char(m, 'YYYY_MM'));
        IF to_regclass('audit.' || part) IS NULL THEN
            EXECUTE format('CREATE TABLE audit.%I PARTITION OF audit.audit_log FOR VALUES FROM (%L) TO (%L)',
                           part, m, (m + interval '1 month')::date);
            n := n + 1;
        END IF;
    END LOOP;
    RETURN n;
END $$;
GRANT EXECUTE ON FUNCTION audit.ensure_partitions(INT) TO app_rw;

-- Crea la partición del mes actual y las 3 siguientes (la partición por defecto debe permanecer vacía)
SELECT audit.ensure_partitions(3);
