             WHERE worksheet_id IN (SELECT id FROM _sicas_worksheet_ids)';
  END IF;

  IF to_regclass('engagement.evidence') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='engagement'
         AND table_name='evidence'
         AND column_name='worksheet_id'
     ) THEN
    EXECUTE 'DELETE FROM engagement.evidence
             WHERE worksheet_id IN (SELECT id FROM _sicas_worksheet_ids)';
  END IF;
END $$;

-- Dependencias directas de auditorías.
DO $$
BEGIN
  IF to_regclass('engagement.evidence') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='engagement'
         AND table_name='evidence'
         AND column_name='audit_id'
     ) THEN
    EXECUTE 'DELETE FROM engagement.evidence
             WHERE audit_id IN (SELECT id FROM _sicas_audit_ids)';
  END IF;

  IF to_regclass('engagement.observations') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='engagement'
         AND table_name='observations'
         AND column_name='audit_id'
     ) THEN
    EXECUTE 'DELETE FROM engagement.observations
             WHERE audit_id IN (SELECT id FROM _sicas_audit_ids)';
  END IF;

  IF to_regclass('engagement.phase_log') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='engagement'
         AND table_name='phase_log'
         AND column_name='audit_id'
     ) THEN
    EXECUTE 'DELETE FROM engagement.phase_log
             WHERE audit_id IN (SELECT id FROM _sicas_audit_ids)';
  END IF;

  IF to_regclass('engagement.signoffs') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='engagement'
         AND table_name='signoffs'
         AND column_name='audit_id'
     ) THEN
    EXECUTE 'DELETE FROM engagement.signoffs
             WHERE audit_id IN (SELECT id FROM _sicas_audit_ids)';
  END IF;

  IF to_regclass('engagement.team') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema='engagement'
         AND table_name='team'
         AND column_name='audit_id'
     ) THEN
    EXECUTE 'DELETE FROM engagement.team
             WHERE audit_id IN (SELECT id FROM _sicas_audit_ids)';
  END IF;

  DELETE FROM engagement.reports
  WHERE id IN (SELECT id FROM _sicas_report_ids);
END $$;

DELETE FROM engagement.worksheets
WHERE id IN (SELECT id FROM _sicas_worksheet_ids);

DELETE FROM engagement.audits
WHERE id IN (SELECT id FROM _sicas_audit_ids);

-- Elimina expedientes solo si ya no los usa otra auditoría.
DO $$
BEGIN
  IF to_regclass('engagement.files') IS NOT NULL THEN
    EXECUTE 'DELETE FROM engagement.files f
             WHERE f.id IN (SELECT file_id FROM _sicas_file_ids)
               AND NOT EXISTS (
                 SELECT 1 FROM engagement.audits a
                 WHERE a.file_id=f.id
               )';
  END IF;
END $$;

-- Restaurar la protección append-only antes del COMMIT.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid='engagement.evidence'::regclass
      AND tgname='trg_evidence_append_only'
      AND NOT tgisinternal
  ) THEN
    EXECUTE 'ALTER TABLE engagement.evidence ENABLE TRIGGER trg_evidence_append_only';
  END IF;
END $$;

COMMIT;

SELECT 'Auditorias restantes' AS dato, count(*) AS cantidad
FROM engagement.audits;

SELECT 'Plantillas maestras restantes' AS dato, count(*) AS cantidad
FROM engagement.templates;

SELECT 'Trigger evidence append-only' AS dato,
       CASE WHEN tgenabled='O' THEN 'ACTIVO' ELSE 'REVISAR' END AS estado
FROM pg_trigger
WHERE tgrelid='engagement.evidence'::regclass
  AND tgname='trg_evidence_append_only'
  AND NOT tgisinternal;
