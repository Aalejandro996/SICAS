-- SICAS
-- Migración 013: registro histórico de cédulas financieras.
-- PASO 2
--
-- SOLO ADITIVO.
-- NO modifica Auditoría de Sistemas.
-- NO modifica engagement.templates.
-- NO toca secrets ni material criptográfico.
--
-- Usa las tablas operativas existentes:
--   engagement.worksheets
--   engagement.items
--   engagement.evidence
--
-- Este paso crea únicamente el registro financiero de la cédula
-- y congela los criterios utilizados en esa auditoría.

BEGIN;

CREATE TABLE IF NOT EXISTS engagement.financial_worksheets (
    worksheet_id UUID PRIMARY KEY
        REFERENCES engagement.worksheets(id) ON DELETE RESTRICT,

    audit_id UUID NOT NULL
        REFERENCES engagement.audits(id) ON DELETE RESTRICT,

    template_code VARCHAR(40) NOT NULL
        REFERENCES engagement.financial_templates(code) ON DELETE RESTRICT,

    template_version INT NOT NULL
        CHECK (template_version >= 1),

    template_sha256 CHAR(64) NOT NULL
        CHECK (template_sha256 ~ '^[0-9a-fA-F]{64}$'),

    criteria_snapshot JSONB NOT NULL
        CHECK (jsonb_typeof(criteria_snapshot) = 'array'),

    created_by UUID NOT NULL
        REFERENCES iam.users(id) ON DELETE RESTRICT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_worksheet_audit_template
    ON engagement.financial_worksheets(audit_id, template_code);

CREATE INDEX IF NOT EXISTS idx_financial_worksheets_audit
    ON engagement.financial_worksheets(audit_id);

CREATE INDEX IF NOT EXISTS idx_financial_worksheets_template
    ON engagement.financial_worksheets(template_code, template_version);


-- ================================================================
-- SNAPSHOT DEL CATÁLOGO FINANCIERO
-- ================================================================

CREATE OR REPLACE FUNCTION engagement.financial_template_snapshot(
    p_template_code VARCHAR(40)
)
RETURNS JSONB
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_snapshot JSONB;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM engagement.financial_templates
        WHERE code = p_template_code
          AND active = TRUE
    ) THEN
        RAISE EXCEPTION
            'Plantilla financiera inexistente o inactiva: %',
            p_template_code
            USING ERRCODE = '22023';
    END IF;

    SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'source_id', fc.source_id,
                'section', fc.section,
                'subsection', fc.subsection,
                'criterion_text', fc.criterion_text,
                'sort_order', fc.sort_order,
                'excel_row', fc.excel_row,
                'weight', fc.weight,
                'metadata', fc.metadata
            )
            ORDER BY fc.sort_order
        ),
        '[]'::jsonb
    )
    INTO v_snapshot
    FROM engagement.financial_criteria fc
    WHERE fc.template_code = p_template_code;

    IF jsonb_array_length(v_snapshot) = 0 THEN
        RAISE EXCEPTION
            'La plantilla financiera % no tiene criterios cargados',
            p_template_code
            USING ERRCODE = '22023';
    END IF;

    RETURN v_snapshot;
END;
$$;


-- ================================================================
-- VALIDACIÓN DE LA CÉDULA FINANCIERA
-- ================================================================

CREATE OR REPLACE FUNCTION engagement.fn_financial_worksheet_guard()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_ws RECORD;
    v_tpl RECORD;
    v_audit RECORD;
    v_snapshot JSONB;
    v_snapshot_hash CHAR(64);
BEGIN

    SELECT
        w.id,
        w.audit_id,
        w.kind,
        w.line
    INTO v_ws
    FROM engagement.worksheets w
    WHERE w.id = NEW.worksheet_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Worksheet inexistente: %',
            NEW.worksheet_id
            USING ERRCODE = '23503';
    END IF;


    SELECT
        a.id,
        a.audit_domain
    INTO v_audit
    FROM engagement.audits a
    WHERE a.id = NEW.audit_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Auditoría inexistente: %',
            NEW.audit_id
            USING ERRCODE = '23503';
    END IF;


    -- PROTECCIÓN: una cédula financiera nunca puede registrarse
    -- dentro de una auditoría de Sistemas.
    IF upper(coalesce(v_audit.audit_domain, '')) <> 'FINANCIERA' THEN
        RAISE EXCEPTION
            'La cédula financiera solo puede pertenecer a una auditoría FINANCIERA. Dominio actual: %',
            v_audit.audit_domain
            USING ERRCODE = '23514';
    END IF;


    SELECT
        ft.code,
        ft.kind,
        ft.line,
        ft.version
    INTO v_tpl
    FROM engagement.financial_templates ft
    WHERE ft.code = NEW.template_code
      AND ft.active = TRUE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Plantilla financiera inexistente o inactiva: %',
            NEW.template_code
            USING ERRCODE = '23503';
    END IF;


    -- Las plantillas transversales tendrán integración propia.
    IF v_tpl.kind = 'TRANSVERSAL' THEN
        RAISE EXCEPTION
            'Las plantillas TRANSVERSAL no se registran como cédula operativa en este paso: %',
            NEW.template_code
            USING ERRCODE = '22023';
    END IF;


    IF v_ws.audit_id <> NEW.audit_id THEN
        RAISE EXCEPTION
            'El worksheet % no pertenece a la auditoría %',
            NEW.worksheet_id,
            NEW.audit_id
            USING ERRCODE = '23514';
    END IF;


    IF v_ws.kind <> v_tpl.kind
       OR v_ws.line <> v_tpl.line THEN

        RAISE EXCEPTION
            'Incompatibilidad worksheet/plantilla: worksheet=(%,%) plantilla=(%,%)',
            v_ws.kind,
            v_ws.line,
            v_tpl.kind,
            v_tpl.line
            USING ERRCODE = '23514';
    END IF;


    IF NEW.template_version <> v_tpl.version THEN
        RAISE EXCEPTION
            'Versión de plantilla inválida. Esperada %, recibida %',
            v_tpl.version,
            NEW.template_version
            USING ERRCODE = '23514';
    END IF;


    v_snapshot :=
        engagement.financial_template_snapshot(
            NEW.template_code
        );


    IF NEW.criteria_snapshot <> v_snapshot THEN
        RAISE EXCEPTION
            'criteria_snapshot no coincide con el catálogo financiero de %',
            NEW.template_code
            USING ERRCODE = '23514';
    END IF;


    v_snapshot_hash :=
        encode(
            digest(
                convert_to(v_snapshot::text, 'UTF8'),
                'sha256'
            ),
            'hex'
        );


    IF lower(NEW.template_sha256) <> lower(v_snapshot_hash) THEN
        RAISE EXCEPTION
            'template_sha256 no coincide con criteria_snapshot para %',
            NEW.template_code
            USING ERRCODE = '23514';
    END IF;


    RETURN NEW;
END;
$$;


DROP TRIGGER IF EXISTS trg_financial_worksheet_guard
    ON engagement.financial_worksheets;

CREATE TRIGGER trg_financial_worksheet_guard
    BEFORE INSERT OR UPDATE
    ON engagement.financial_worksheets
    FOR EACH ROW
    EXECUTE FUNCTION engagement.fn_financial_worksheet_guard();


-- ================================================================
-- INMUTABILIDAD DEL SNAPSHOT HISTÓRICO
-- ================================================================

CREATE OR REPLACE FUNCTION engagement.fn_financial_worksheet_immutable()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN

    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'La cédula financiera registrada es inmutable'
            USING ERRCODE = '55000';
    END IF;


    IF TG_OP = 'UPDATE' THEN

        IF NEW.worksheet_id <> OLD.worksheet_id
           OR NEW.audit_id <> OLD.audit_id
           OR NEW.template_code <> OLD.template_code
           OR NEW.template_version <> OLD.template_version
           OR NEW.template_sha256 <> OLD.template_sha256
           OR NEW.criteria_snapshot <> OLD.criteria_snapshot
           OR NEW.created_by <> OLD.created_by
           OR NEW.created_at <> OLD.created_at THEN

            RAISE EXCEPTION
                'La cédula financiera registrada es inmutable'
                USING ERRCODE = '55000';
        END IF;

        RETURN NEW;
    END IF;


    RETURN NEW;
END;
$$;


DROP TRIGGER IF EXISTS trg_financial_worksheet_immutable
    ON engagement.financial_worksheets;

CREATE TRIGGER trg_financial_worksheet_immutable
    BEFORE UPDATE OR DELETE
    ON engagement.financial_worksheets
    FOR EACH ROW
    EXECUTE FUNCTION engagement.fn_financial_worksheet_immutable();


-- ================================================================
-- REGISTRO DE UNA CÉDULA FINANCIERA
-- ================================================================

CREATE OR REPLACE FUNCTION engagement.register_financial_worksheet(
    p_worksheet_id UUID,
    p_template_code VARCHAR(40),
    p_created_by UUID
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    v_ws RECORD;
    v_tpl RECORD;
    v_audit RECORD;
    v_snapshot JSONB;
    v_hash CHAR(64);
    v_id UUID;
BEGIN

    SELECT
        w.id,
        w.audit_id,
        w.kind,
        w.line
    INTO v_ws
    FROM engagement.worksheets w
    WHERE w.id = p_worksheet_id
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Worksheet inexistente: %',
            p_worksheet_id
            USING ERRCODE = '23503';
    END IF;


    SELECT
        a.id,
        a.audit_domain
    INTO v_audit
    FROM engagement.audits a
    WHERE a.id = v_ws.audit_id
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Auditoría inexistente: %',
            v_ws.audit_id
            USING ERRCODE = '23503';
    END IF;


    IF upper(coalesce(v_audit.audit_domain, '')) <> 'FINANCIERA' THEN
        RAISE EXCEPTION
            'La cédula financiera solo puede registrarse en auditorías FINANCIERA'
            USING ERRCODE = '23514';
    END IF;


    SELECT
        ft.code,
        ft.kind,
        ft.line,
        ft.version
    INTO v_tpl
    FROM engagement.financial_templates ft
    WHERE ft.code = p_template_code
      AND ft.active = TRUE
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'Plantilla financiera inexistente o inactiva: %',
            p_template_code
            USING ERRCODE = '23503';
    END IF;


    IF v_tpl.kind = 'TRANSVERSAL' THEN
        RAISE EXCEPTION
            'La plantilla transversal se integrará en su paso específico: %',
            p_template_code
            USING ERRCODE = '22023';
    END IF;


    IF v_ws.kind <> v_tpl.kind
       OR v_ws.line <> v_tpl.line THEN

        RAISE EXCEPTION
            'El worksheet (%,%) no corresponde a la plantilla (%,%)',
            v_ws.kind,
            v_ws.line,
            v_tpl.kind,
            v_tpl.line
            USING ERRCODE = '23514';
    END IF;


    v_snapshot :=
        engagement.financial_template_snapshot(
            p_template_code
        );


    v_hash :=
        encode(
            digest(
                convert_to(v_snapshot::text, 'UTF8'),
                'sha256'
            ),
            'hex'
        );


    INSERT INTO engagement.financial_worksheets (
        worksheet_id,
        audit_id,
        template_code,
        template_version,
        template_sha256,
        criteria_snapshot,
        created_by
    )
    VALUES (
        p_worksheet_id,
        v_ws.audit_id,
        p_template_code,
        v_tpl.version,
        v_hash,
        v_snapshot,
        p_created_by
    )
    RETURNING worksheet_id
    INTO v_id;


    RETURN v_id;

EXCEPTION
    WHEN unique_violation THEN
        RAISE EXCEPTION
            'La cédula financiera ya está registrada para esta auditoría/plantilla'
            USING ERRCODE = '23505';
END;
$$;


-- ================================================================
-- VISTA DE CONSULTA
-- ================================================================

CREATE OR REPLACE VIEW engagement.financial_worksheet_criteria AS
SELECT
    fw.worksheet_id,
    fw.audit_id,
    fw.template_code,
    fw.template_version,
    x.sort_order,
    x.source_id,
    x.section,
    x.subsection,
    x.criterion_text,
    x.excel_row,
    x.weight,
    x.metadata
FROM engagement.financial_worksheets fw
CROSS JOIN LATERAL jsonb_to_recordset(
    fw.criteria_snapshot
) AS x(
    source_id TEXT,
    section TEXT,
    subsection TEXT,
    criterion_text TEXT,
    sort_order INT,
    excel_row INT,
    weight NUMERIC(10,4),
    metadata JSONB
);


-- ================================================================
-- PERMISOS
-- ================================================================

GRANT SELECT, INSERT, UPDATE
    ON engagement.financial_worksheets
    TO app_rw;

GRANT SELECT
    ON engagement.financial_worksheet_criteria
    TO app_rw;

GRANT EXECUTE
    ON FUNCTION engagement.financial_template_snapshot(VARCHAR)
    TO app_rw;

GRANT EXECUTE
    ON FUNCTION engagement.register_financial_worksheet(
        UUID,
        VARCHAR,
        UUID
    )
    TO app_rw;


COMMIT;
