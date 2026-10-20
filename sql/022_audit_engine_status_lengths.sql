-- SICAS - Migración 022:
-- Permitir los estados completos del motor y de los hallazgos.
-- Aditiva: no elimina ni modifica filas existentes.
BEGIN;

ALTER TABLE engine.runs
    ALTER COLUMN status TYPE VARCHAR(32);

ALTER TABLE engine.findings
    ALTER COLUMN status TYPE VARCHAR(32);

COMMIT;
