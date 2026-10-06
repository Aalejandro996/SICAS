-- 011: Dominio y responsable de las unidades de Auditoría de Sistemas.
-- No altera las funciones de GERENCIA ni CONTRALOR.
BEGIN;

ALTER TABLE engagement.units
    ADD COLUMN IF NOT EXISTS audit_domain VARCHAR(12) NOT NULL DEFAULT 'GENERAL';

ALTER TABLE engagement.units
    ADD COLUMN IF NOT EXISTS responsible_name VARCHAR(200);

ALTER TABLE engagement.units
    ADD COLUMN IF NOT EXISTS responsible_role VARCHAR(200);

ALTER TABLE engagement.units
    DROP CONSTRAINT IF EXISTS units_audit_domain_check;

ALTER TABLE engagement.units
    ADD CONSTRAINT units_audit_domain_check
    CHECK (audit_domain IN ('GENERAL','FINANCIERA','SISTEMAS'));

INSERT INTO engagement.units (code, name, kind, audit_domain, responsible_name, responsible_role)
VALUES
    ('1', 'SISTEMAS', 'UNIDAD', 'SISTEMAS', NULL, 'JEFE SISTEMAS'),
    ('2', 'PRUEBAS Y CERTIFICACIONES', 'UNIDAD', 'SISTEMAS', NULL, 'JEFE DE PRUEBAS Y CERTIFICACIONES'),
    ('3', 'SISTEMA EMPRESAS', 'UNIDAD', 'SISTEMAS', NULL, 'JEFE DE SISTEMA EMPRESAS'),
    ('4', 'SERVIDORES Y BASE DE DATOS', 'UNIDAD', 'SISTEMAS', 'Juan Mercado', 'JEFE DE SERVIDORES Y BASE DE DATOS'),
    ('5', 'REDES Y TELECOM.', 'UNIDAD', 'SISTEMAS', 'Angel Aparicio', 'JEFE DE REDES Y TELECOM.'),
    ('6', 'MICROINFORMÁTICA', 'UNIDAD', 'SISTEMAS', 'Moises Ramirez', 'JEFE DE MICROINFORMÁTICA'),
    ('7', 'CIBERSEGURIDAD', 'UNIDAD', 'SISTEMAS', 'Angel Yánez', 'JEFE DE CIBERSEGURIDAD'),
    ('8', 'GERENTE DE SISTEMAS', 'UNIDAD', 'SISTEMAS', 'Carla de Oliveira', 'GERENTE DE SISTEMAS'),
    ('9', 'VICE PRESIDENCIA TI', 'UNIDAD', 'SISTEMAS', 'Edgar Rodríguez', 'VICE PRESIDENCIA TI')
ON CONFLICT (code) DO UPDATE
SET
    name = EXCLUDED.name,
    kind = EXCLUDED.kind,
    audit_domain = EXCLUDED.audit_domain,
    responsible_name = EXCLUDED.responsible_name,
    responsible_role = EXCLUDED.responsible_role,
    active = TRUE;

COMMIT;
