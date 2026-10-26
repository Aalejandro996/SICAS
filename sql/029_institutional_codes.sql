-- 029: codificación institucional (docs/CODIFICACIÓN DE INFORMES.docx).
--   Expediente: TIPO-COMPAÑÍA-CORRELATIVO-AÑO          (S-SC-001-2026)
--   Auditoría : código del expediente + -A<n>          (S-SC-001-2026-A1)
--   Informe   : SIGLAS-PROCESO-TIPO-COMPAÑÍA-CORR-AÑO  (P-S-G-SC-001-2026)
-- Los expedientes, auditorías e informes existentes se recodifican; el código anterior se
-- conserva en legacy_code y el cambio queda en la bitácora. El contenido ya generado de los
-- informes (y sus firmas) no se modifica: conserva el código vigente al emitirse.

ALTER TABLE engagement.files
    ADD COLUMN IF NOT EXISTS audit_type VARCHAR(2),
    ADD COLUMN IF NOT EXISTS company VARCHAR(4),
    ADD COLUMN IF NOT EXISTS fiscal_year INTEGER,
    ADD COLUMN IF NOT EXISTS legacy_code VARCHAR(20);
ALTER TABLE engagement.files ALTER COLUMN code TYPE VARCHAR(30);

ALTER TABLE engagement.audits
    ADD COLUMN IF NOT EXISTS plan_type VARCHAR(1),
    ADD COLUMN IF NOT EXISTS process VARCHAR(2),
    ADD COLUMN IF NOT EXISTS frequency VARCHAR(1),
    ADD COLUMN IF NOT EXISTS report_company VARCHAR(2),
    ADD COLUMN IF NOT EXISTS legacy_code VARCHAR(20);
ALTER TABLE engagement.audits ALTER COLUMN code TYPE VARCHAR(30);

ALTER TABLE engagement.reports ADD COLUMN IF NOT EXISTS code VARCHAR(30);

-- ---------------------------------------------------------------- recodificación de expedientes
UPDATE engagement.files f SET legacy_code = f.code WHERE f.legacy_code IS NULL;

WITH typed AS (
    SELECT f.id, f.created_at, f.legacy_code,
           CASE WHEN f.audit_domain = 'SISTEMAS' THEN 'S'
                WHEN u.kind = 'SUCURSAL' THEN 'A'
                ELSE 'C' END AS t,
           'SC' AS c,
           extract(year FROM f.created_at)::int AS y
    FROM engagement.files f JOIN engagement.units u ON u.id = f.unit_id
    WHERE f.audit_type IS NULL
), numbered AS (
    SELECT id, t, c, y, row_number() OVER (PARTITION BY t, c, y ORDER BY created_at, legacy_code) AS n FROM typed
)
UPDATE engagement.files f
SET audit_type = n.t, company = n.c, fiscal_year = n.y,
    code = n.t || '-' || n.c || '-' || lpad(n.n::text, 3, '0') || '-' || n.y
FROM numbered n WHERE n.id = f.id;

-- ---------------------------------------------------------------- recodificación de auditorías
UPDATE engagement.audits a SET legacy_code = a.code WHERE a.legacy_code IS NULL;

WITH numbered AS (
    SELECT a.id, f.code AS file_code,
           row_number() OVER (PARTITION BY a.file_id ORDER BY a.created_at, a.legacy_code) AS n
    FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id
    WHERE a.plan_type IS NULL
)
UPDATE engagement.audits a
SET code = n.file_code || '-A' || n.n,
    plan_type = 'P',
    process = CASE a.audit_domain WHEN 'SISTEMAS' THEN 'S' WHEN 'FINANCIERA' THEN 'F' ELSE 'O' END,
    frequency = 'G',
    report_company = 'SC'
FROM numbered n WHERE n.id = a.id;

-- ---------------------------------------------------------------- códigos de informes existentes
-- Un código por auditoría y tipo de informe (las versiones comparten el código).
WITH groups AS (
    SELECT r.audit_id, r.kind, min(r.created_at) AS first_at,
           a.plan_type || '-' || a.process || '-' || a.frequency || '-' || a.report_company AS prefix
    FROM engagement.reports r JOIN engagement.audits a ON a.id = r.audit_id
    WHERE r.code IS NULL
    GROUP BY r.audit_id, r.kind, a.plan_type, a.process, a.frequency, a.report_company
), numbered AS (
    SELECT audit_id, kind, prefix, extract(year FROM first_at)::int AS y,
           row_number() OVER (PARTITION BY prefix, extract(year FROM first_at) ORDER BY first_at, audit_id, kind) AS n
    FROM groups
)
UPDATE engagement.reports r
SET code = n.prefix || '-' || lpad(n.n::text, 3, '0') || '-' || n.y
FROM numbered n WHERE n.audit_id = r.audit_id AND n.kind = r.kind;

-- ---------------------------------------------------------------- bitácora del cambio
INSERT INTO engagement.change_events (audit_id, entity_type, entity_id, action, changes, reason, audit_phase, actor_id, actor_username)
SELECT a.id, 'audit', a.id::text, 'CODES_RECODED',
       jsonb_build_object('audit_code', jsonb_build_object('before', a.legacy_code, 'after', a.code),
                          'file_code', jsonb_build_object('before', f.legacy_code, 'after', f.code)),
       'Adopción de la codificación institucional de expedientes, auditorías e informes',
       a.phase, a.created_by, 'sistema'
FROM engagement.audits a JOIN engagement.files f ON f.id = a.file_id
WHERE a.legacy_code IS NOT NULL AND a.legacy_code <> a.code;

-- ---------------------------------------------------------------- reglas
ALTER TABLE engagement.files ALTER COLUMN audit_type SET NOT NULL, ALTER COLUMN company SET NOT NULL,
    ALTER COLUMN fiscal_year SET NOT NULL;
ALTER TABLE engagement.files
    ADD CONSTRAINT files_audit_type_check CHECK (audit_type IN ('P', 'A', 'C', 'S', 'LC')),
    ADD CONSTRAINT files_company_check CHECK (company IN ('SC', 'ASN', 'CAR', 'BTM', 'RPF', 'INSG', 'SGRK', 'VIDP', 'AGC', 'VEN'));

ALTER TABLE engagement.audits ALTER COLUMN plan_type SET NOT NULL, ALTER COLUMN process SET NOT NULL,
    ALTER COLUMN frequency SET NOT NULL, ALTER COLUMN report_company SET NOT NULL;
ALTER TABLE engagement.audits
    ADD CONSTRAINT audits_plan_type_check CHECK (plan_type IN ('P', 'E')),
    ADD CONSTRAINT audits_process_check CHECK (process IN ('O', 'T', 'A', 'C', 'S', 'E', 'F', 'LC', 'IS', 'CR')),
    ADD CONSTRAINT audits_frequency_check CHECK (frequency IN ('S', 'G', 'E')),
    ADD CONSTRAINT audits_report_company_check CHECK (report_company IN ('SC', 'CR'));

CREATE INDEX IF NOT EXISTS reports_code_idx ON engagement.reports (code);

-- ---------------------------------------------------------------- observaciones consolidadas
-- Una observación automática puede cubrir varios controles del mismo dominio (covered_items).
-- Las observaciones automáticas individuales que se consolidan no se borran: quedan
-- reemplazadas (superseded_by) y fuera de los listados, el informe y el PAC.
ALTER TABLE engagement.observations
    ADD COLUMN IF NOT EXISTS covered_items UUID[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS superseded_by UUID REFERENCES engagement.observations(id);
UPDATE engagement.observations SET covered_items = ARRAY[item_id] WHERE item_id IS NOT NULL AND covered_items = '{}';
