-- 001: IAM + Audit trail inmutable  (PostgreSQL 14+)
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS iam;
CREATE SCHEMA IF NOT EXISTS audit;

-- ===================== IAM =====================
CREATE TABLE iam.users (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username             VARCHAR(80)  NOT NULL UNIQUE,
    email                VARCHAR(255) NOT NULL UNIQUE,
    full_name            VARCHAR(200) NOT NULL,
    password_hash        TEXT         NOT NULL,           -- Argon2id
    is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
    failed_attempts      SMALLINT     NOT NULL DEFAULT 0,
    locked_until         TIMESTAMPTZ,
    password_changed_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    must_change_password BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at        TIMESTAMPTZ,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_by           UUID REFERENCES iam.users(id)
);

CREATE TABLE iam.mfa_devices (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
    type         VARCHAR(20) NOT NULL DEFAULT 'totp',
    secret_enc   TEXT NOT NULL,                           -- AES-256-GCM a nivel de aplicación (KeyRing)
    confirmed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE iam.roles (
    id          SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        VARCHAR(40) NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE iam.permissions (
    id          INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code        VARCHAR(80) NOT NULL UNIQUE,
    module      VARCHAR(40) NOT NULL,
    description TEXT
);

CREATE TABLE iam.role_permissions (
    role_id       SMALLINT NOT NULL REFERENCES iam.roles(id),
    permission_id INT      NOT NULL REFERENCES iam.permissions(id),
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE iam.user_roles (
    user_id    UUID     NOT NULL REFERENCES iam.users(id),
    role_id    SMALLINT NOT NULL REFERENCES iam.roles(id),
    granted_by UUID     REFERENCES iam.users(id),
    approved_by UUID    REFERENCES iam.users(id),         -- doble control en asignación
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id),
    CHECK (approved_by IS NULL OR approved_by <> granted_by)
);

CREATE TABLE iam.sod_conflicts (
    permission_a VARCHAR(80) NOT NULL REFERENCES iam.permissions(code),
    permission_b VARCHAR(80) NOT NULL REFERENCES iam.permissions(code),
    reason       TEXT NOT NULL,
    PRIMARY KEY (permission_a, permission_b)
);

CREATE TABLE iam.refresh_tokens (
    jti        UUID PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES iam.users(id),
    issued_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    ip_address INET,
    user_agent TEXT
);

-- ===================== AUDIT TRAIL INMUTABLE =====================
CREATE TABLE audit.audit_log (
    id             BIGINT GENERATED ALWAYS AS IDENTITY,
    occurred_at    TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    request_id     UUID,
    actor_id       UUID,                                  -- sin FK: el log nunca debe bloquear borrados de usuarios
    actor_username VARCHAR(80),
    actor_roles    TEXT[],
    action         VARCHAR(60) NOT NULL,
    entity_type    VARCHAR(60),
    entity_id      TEXT,
    outcome        VARCHAR(10) NOT NULL CHECK (outcome IN ('SUCCESS','FAILURE','DENIED')),
    ip_address     INET,
    user_agent     TEXT,
    before_data    JSONB,
    after_data     JSONB,
    metadata       JSONB,
    prev_hash      BYTEA,
    row_hash       BYTEA NOT NULL,
    PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);

-- Particiones: automatizar con pg_partman o tarea programada (ejemplo)
CREATE TABLE audit.audit_log_2026_09 PARTITION OF audit.audit_log
    FOR VALUES FROM ('2026-09-01') TO ('2026-10-01');
CREATE TABLE audit.audit_log_2026_10 PARTITION OF audit.audit_log
    FOR VALUES FROM ('2026-10-01') TO ('2026-11-01');

-- Partición por defecto: ningún evento de auditoría se pierde si falta la partición del mes.
CREATE TABLE audit.audit_log_default PARTITION OF audit.audit_log DEFAULT;

CREATE INDEX ON audit.audit_log (actor_id, occurred_at DESC);
CREATE INDEX ON audit.audit_log (entity_type, entity_id);
CREATE INDEX ON audit.audit_log (action, occurred_at DESC);

-- Hash de fila: UNA sola definición, usada por el trigger y por la verificación.
-- Fecha en UTC con formato fijo (no depende de la zona horaria de la sesión).
CREATE OR REPLACE FUNCTION audit.fn_row_digest(
    p_prev BYTEA, p_at TIMESTAMPTZ, p_request UUID, p_actor UUID, p_action TEXT, p_etype TEXT,
    p_eid TEXT, p_outcome TEXT, p_before JSONB, p_after JSONB, p_meta JSONB) RETURNS BYTEA
LANGUAGE sql IMMUTABLE AS $$
    SELECT digest(
        coalesce(encode(p_prev,'hex'),'') || '|' ||
        to_char(p_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US') || '|' ||
        coalesce(p_request::text,'') || '|' || coalesce(p_actor::text,'') || '|' ||
        p_action || '|' || coalesce(p_etype,'') || '|' || coalesce(p_eid,'') || '|' || p_outcome || '|' ||
        coalesce(p_before::text,'') || '|' || coalesce(p_after::text,'') || '|' || coalesce(p_meta::text,''),
        'sha256')
$$;

-- Hash encadenado: cada fila depende de la anterior
CREATE OR REPLACE FUNCTION audit.fn_chain_hash() RETURNS trigger AS $$
DECLARE v_prev BYTEA;
BEGIN
    PERFORM pg_advisory_xact_lock(884422);                -- serializa la cadena
    SELECT row_hash INTO v_prev FROM audit.audit_log ORDER BY id DESC LIMIT 1;
    NEW.prev_hash := v_prev;
    NEW.row_hash  := audit.fn_row_digest(v_prev, NEW.occurred_at, NEW.request_id, NEW.actor_id, NEW.action,
                                         NEW.entity_type, NEW.entity_id, NEW.outcome,
                                         NEW.before_data, NEW.after_data, NEW.metadata);
    RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_chain_hash BEFORE INSERT ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.fn_chain_hash();

CREATE OR REPLACE FUNCTION audit.fn_block_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log es inmutable: % no permitido', TG_OP;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_no_update_delete BEFORE UPDATE OR DELETE ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.fn_block_mutation();
CREATE TRIGGER trg_no_truncate BEFORE TRUNCATE ON audit.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit.fn_block_mutation();

-- Privilegios (crear antes los roles app_rw y audit_reader)
REVOKE ALL ON SCHEMA audit FROM PUBLIC;
GRANT USAGE ON SCHEMA audit TO app_rw, audit_reader;
GRANT INSERT ON audit.audit_log TO app_rw;                -- la app solo inserta
GRANT SELECT ON audit.audit_log TO audit_reader;
