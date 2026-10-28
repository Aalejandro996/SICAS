-- 040: Informe Ejecutivo e Informe de Documentación.
--
-- El informe general pasa a ser:
--   EJECUTIVO      auditorías CERRADAS en un trimestre, semestre o año (por su fecha de cierre); ambos dominios.
--   DOCUMENTACION  (Sistemas) auditorías en fase de Documentación y lo obtenido de la carta de solicitud.
-- Informes existentes: el que no cumple (alguna auditoría no está cerrada) se elimina; el que cumple se actualiza
-- con la data vigente al abrirlo (needs_refresh), como Informe Ejecutivo del año en que se cerraron sus auditorías.

ALTER TABLE engagement.general_reports ADD COLUMN IF NOT EXISTS report_kind VARCHAR(14) NOT NULL DEFAULT 'EJECUTIVO';
ALTER TABLE engagement.general_reports DROP CONSTRAINT IF EXISTS general_reports_report_kind_check;
ALTER TABLE engagement.general_reports ADD CONSTRAINT general_reports_report_kind_check CHECK (report_kind IN ('EJECUTIVO', 'DOCUMENTACION'));
ALTER TABLE engagement.general_reports ADD COLUMN IF NOT EXISTS period JSONB;
ALTER TABLE engagement.general_reports ADD COLUMN IF NOT EXISTS needs_refresh BOOLEAN NOT NULL DEFAULT FALSE;

GRANT DELETE ON engagement.general_reports, engagement.general_report_events, engagement.general_report_acks TO app_rw;

-- No cumple: alguna auditoría del informe no está cerrada.
DELETE FROM engagement.general_report_acks k USING engagement.general_reports r WHERE k.report_id = r.id AND r.period IS NULL
  AND EXISTS (SELECT 1 FROM unnest(r.audit_ids) aid LEFT JOIN engagement.audits a ON a.id = aid WHERE a.status IS DISTINCT FROM 'CLOSED');
DELETE FROM engagement.general_report_events e USING engagement.general_reports r WHERE e.report_id = r.id AND r.period IS NULL
  AND EXISTS (SELECT 1 FROM unnest(r.audit_ids) aid LEFT JOIN engagement.audits a ON a.id = aid WHERE a.status IS DISTINCT FROM 'CLOSED');
DELETE FROM engagement.general_reports r WHERE r.period IS NULL
  AND EXISTS (SELECT 1 FROM unnest(r.audit_ids) aid LEFT JOIN engagement.audits a ON a.id = aid WHERE a.status IS DISTINCT FROM 'CLOSED');

-- Cumple: se actualiza con la data vigente al abrirlo, como Informe Ejecutivo del año de cierre más reciente.
UPDATE engagement.general_reports r SET needs_refresh = TRUE, report_kind = 'EJECUTIVO',
       period = jsonb_build_object('type', 'ANUAL', 'n', 1, 'year',
                (SELECT COALESCE(max(EXTRACT(YEAR FROM a.pac_sent_at)), EXTRACT(YEAR FROM r.created_at))::int
                 FROM unnest(r.audit_ids) aid JOIN engagement.audits a ON a.id = aid))
WHERE r.period IS NULL;

-- Reparación: las cédulas de Sistemas creadas después de la migración 038 quedaron sin sus controles (una fila por
-- control del cuestionario). Se crean las filas que faltan a partir de los criterios de la cédula.
INSERT INTO engagement.items (id, worksheet_id, ref, source, updated_by)
SELECT gen_random_uuid(), w.id, c->>'code', 'ONLINE', w.created_by
FROM engagement.worksheets w CROSS JOIN LATERAL jsonb_array_elements(w.criteria) c
WHERE w.kind = 'SISTEMAS' AND c->>'code' IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM engagement.items i WHERE i.worksheet_id = w.id)
ON CONFLICT (worksheet_id, ref) DO NOTHING;
