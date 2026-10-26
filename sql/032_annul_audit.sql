-- 032: anulación lógica de auditorías creadas por error y anulación de S-SC-005-2026-A3 (solicitada por el usuario).
--
-- No se borra físicamente: la bitácora (change_events) y el audit trail son de solo inserción y la
-- referencian. La auditoría anulada queda con estado ANULADA, oculta en las listas y en los indicadores,
-- y su código se libera (sufijo -ANULADA) para que el correlativo -A<n> del expediente no quede con un hueco.

DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'engagement.audits'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%IN_PROGRESS%'
  LOOP
    EXECUTE format('ALTER TABLE engagement.audits DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
ALTER TABLE engagement.audits ADD CONSTRAINT audits_status_check CHECK (status IN ('IN_PROGRESS', 'CLOSED', 'ANULADA'));
ALTER TABLE engagement.audits ADD COLUMN IF NOT EXISTS annulled_at TIMESTAMPTZ;
ALTER TABLE engagement.audits ADD COLUMN IF NOT EXISTS annulled_code VARCHAR(30);
ALTER TABLE engagement.audits ADD COLUMN IF NOT EXISTS annulled_reason TEXT;
ALTER TABLE engagement.audits ADD CONSTRAINT audits_annulled_consistent
    CHECK ((status = 'ANULADA') = (annulled_at IS NOT NULL));

-- Solo se anula si sigue en curso y no tiene informes (ni, por tanto, firmas). Si no cumple, se informa y no se toca.
DO $$
DECLARE a RECORD;
BEGIN
  SELECT au.id, au.code, au.phase, au.created_by INTO a
  FROM engagement.audits au WHERE au.code = 'S-SC-005-2026-A3' AND au.status = 'IN_PROGRESS';
  IF NOT FOUND THEN
    RAISE NOTICE 'S-SC-005-2026-A3 no existe o no está en curso: no se anula nada';
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM engagement.reports r WHERE r.audit_id = a.id) THEN
    RAISE NOTICE 'S-SC-005-2026-A3 tiene informes generados: no se anula automáticamente';
    RETURN;
  END IF;
  UPDATE engagement.audits
     SET status = 'ANULADA', annulled_at = now(), annulled_code = a.code, code = a.code || '-ANULADA',
         annulled_reason = 'Creada por error y sobrante en el expediente S-SC-005-2026 (anulación solicitada por el usuario)'
   WHERE id = a.id;
  INSERT INTO engagement.change_events (audit_id, entity_type, entity_id, action, changes, reason, audit_phase, actor_id, actor_username)
  VALUES (a.id, 'audit', a.id::text, 'AUDIT_ANNULLED',
          jsonb_build_object('status', jsonb_build_object('before', 'IN_PROGRESS', 'after', 'ANULADA'),
                             'code', jsonb_build_object('before', a.code, 'after', a.code || '-ANULADA')),
          'Creada por error y sobrante en el expediente S-SC-005-2026 (anulación solicitada por el usuario)',
          a.phase, a.created_by, 'sistema (migración 032)');
  RAISE NOTICE 'S-SC-005-2026-A3 anulada';
END $$;
