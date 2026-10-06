-- 010: Cuestionario oficial de Auditoría de Sistemas / ERPs TI.
-- Amplía las cédulas existentes sin alterar las de Suscripción/Reclamo.
BEGIN;

ALTER TABLE engagement.templates DROP CONSTRAINT IF EXISTS templates_kind_check;
ALTER TABLE engagement.templates DROP CONSTRAINT IF EXISTS templates_line_check;
ALTER TABLE engagement.templates
    ADD CONSTRAINT templates_kind_check
    CHECK (kind IN ('SUSCRIPCION','RECLAMO','SISTEMAS'));
ALTER TABLE engagement.templates
    ADD CONSTRAINT templates_line_check
    CHECK (line IN ('AUTO','PATRIMONIAL','PERSONAL','ERP_TI'));

ALTER TABLE engagement.worksheets DROP CONSTRAINT IF EXISTS worksheets_kind_check;
ALTER TABLE engagement.worksheets DROP CONSTRAINT IF EXISTS worksheets_line_check;
ALTER TABLE engagement.worksheets
    ADD CONSTRAINT worksheets_kind_check
    CHECK (kind IN ('SUSCRIPCION','RECLAMO','SISTEMAS'));
ALTER TABLE engagement.worksheets
    ADD CONSTRAINT worksheets_line_check
    CHECK (line IN ('AUTO','PATRIMONIAL','PERSONAL','ERP_TI'));

COMMIT;
