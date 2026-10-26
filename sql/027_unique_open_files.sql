-- 027: un solo expediente abierto por unidad y período revisado.
-- Las auditorías adicionales de la misma unidad y período se abren dentro del expediente existente.
-- Si ya hubiera duplicados abiertos, el índice no se crea (la API igual impide crear nuevos)
-- y se informa para depurarlos manualmente sin alterar datos aquí.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM engagement.files WHERE status = 'OPEN'
    GROUP BY unit_id, period_from, period_to HAVING count(*) > 1
  ) THEN
    RAISE NOTICE 'Hay expedientes abiertos duplicados por unidad y período: no se crea el índice único';
  ELSE
    CREATE UNIQUE INDEX IF NOT EXISTS files_open_unit_period_uq
        ON engagement.files (unit_id, period_from, period_to) WHERE status = 'OPEN';
  END IF;
END $$;
