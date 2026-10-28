-- 041: Sin Gerente en el cargo y cambio de equipo por el Jefe de Auditoría.
--
-- Informe final: si al aprobar el Jefe no hay ningún usuario activo con el rol Gerencia (ni suplente vigente de
-- Gerencia), el informe pasa directamente al Contralor y queda marcado «Gerencia omitida: sin Gerente en el cargo».
-- Una devolución quita la marca; al volver a haber Gerente, el flujo vuelve a ser completo.
ALTER TABLE engagement.reports ADD COLUMN IF NOT EXISTS gerencia_omitted BOOLEAN NOT NULL DEFAULT FALSE;

-- El Jefe de Auditoría del dominio puede reemplazar el equipo auditor de una auditoría en curso.
GRANT DELETE ON engagement.team TO app_rw;
