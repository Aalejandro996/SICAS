-- 038: Las cédulas de muestra (suscripción, reclamo, cuentas por pagar/cobrar, gestión administrativa) ya no se
-- crean con una fila por criterio: cada fila es un número de póliza o siniestro que agrega el auditor.
-- Se retiran las filas precargadas con el código de un criterio que siguen vacías (sin respuestas, observación,
-- excepción, ajuste manual, evidencias ni observaciones). Las que ya tienen trabajo se conservan.
DELETE FROM engagement.items i
USING engagement.worksheets w
WHERE i.worksheet_id = w.id
  AND w.kind NOT IN ('SISTEMAS', 'TI_SUC', 'CARTELERA', 'ADS', 'LOPCYMAT', 'SERV_SUC')
  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(w.criteria) c WHERE c ? 'block')
  AND EXISTS (SELECT 1 FROM jsonb_array_elements(w.criteria) c WHERE c->>'code' = i.ref)
  AND COALESCE(i.results, '{}'::jsonb) = '{}'::jsonb
  AND i.observation IS NULL
  AND i.info_exception IS NULL
  AND i.manual_score IS NULL
  AND COALESCE(i.phase_results, '{}'::jsonb) = '{}'::jsonb
  AND NOT EXISTS (SELECT 1 FROM engagement.evidence e WHERE e.item_id = i.id)
  AND NOT EXISTS (SELECT 1 FROM engagement.observations o WHERE o.item_id = i.id);
