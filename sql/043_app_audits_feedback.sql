-- 043: Auditoría de aplicativos (sistemas lógicos) y retroalimentación del motor de reglas.
-- 1. Inventario de aplicativos: una «unidad» de tipo APLICATIVO (dominio Sistemas) con su ficha técnica.
-- 2. Auditoría de tipo APLICATIVO: cuestionario por plantilla (AcselX), encuestas direccionadas por área,
--    pruebas técnicas sustantivas, matriz de riesgos y madurez COBIT/CMMI ajustables por el auditor.
-- 3. Catálogo normativo único (ISO 27001:2022, COBIT 2019, legislación venezolana y SUDEASEG).
-- 4. Retroalimentación: decisiones del auditor, propuestas de reglas y reglas aprobadas por el Contralor.

ALTER TABLE engagement.units DROP CONSTRAINT IF EXISTS units_kind_check;
ALTER TABLE engagement.units ADD CONSTRAINT units_kind_check CHECK (kind IN ('SUCURSAL', 'UNIDAD', 'APLICATIVO'));

ALTER TABLE engagement.audits DROP CONSTRAINT IF EXISTS audits_audit_kind_check;
ALTER TABLE engagement.audits ADD CONSTRAINT audits_audit_kind_check
    CHECK (audit_kind IN ('SISTEMAS', 'APLICATIVO', 'OPERATIVA', 'ESPECIAL', 'ADMINISTRATIVA', 'FINANCIERA'));

CREATE TABLE IF NOT EXISTS engagement.applications (
    unit_id        INTEGER PRIMARY KEY REFERENCES engagement.units(id),
    vendor         VARCHAR(120),
    product        VARCHAR(120) NOT NULL,
    version        VARCHAR(60),
    category       VARCHAR(10) NOT NULL DEFAULT 'CORE' CHECK (category IN ('CORE', 'ERP', 'CONTABLE', 'NOMINA', 'CANAL', 'OTRO')),
    model          VARCHAR(12) NOT NULL DEFAULT 'TERCERIZADO' CHECK (model IN ('PROPIO', 'TERCERIZADO', 'SAAS', 'NUBE')),
    db_engine      VARCHAR(80),
    hosting        VARCHAR(120),
    criticality    VARCHAR(5) NOT NULL DEFAULT 'ALTA' CHECK (criticality IN ('ALTA', 'MEDIA', 'BAJA')),
    owner_unit_id  INTEGER REFERENCES engagement.units(id),
    custodian      VARCHAR(160),
    users_count    INTEGER CHECK (users_count IS NULL OR users_count >= 0),
    modules        TEXT,
    interfaces     TEXT,
    template_code  VARCHAR(20) NOT NULL DEFAULT 'ACSELX',
    params         JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by     UUID,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pruebas técnicas sustantivas (programa BD e interfaz contable) por auditoría.
CREATE TABLE IF NOT EXISTS engagement.app_tests (
    audit_id    UUID NOT NULL REFERENCES engagement.audits(id),
    code        VARCHAR(20) NOT NULL,
    result      VARCHAR(10) NOT NULL CHECK (result IN ('CUMPLE', 'NO_CUMPLE', 'NO_APLICA', 'PENDIENTE')),
    detail      TEXT,
    query_used  TEXT,
    evidence_id UUID REFERENCES engagement.evidence(id),
    updated_by  UUID NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (audit_id, code)
);

-- Ajustes humanos de la matriz de riesgos y de la madurez (prevalecen sobre lo calculado).
CREATE TABLE IF NOT EXISTS engagement.app_risk_overrides (
    audit_id    UUID NOT NULL REFERENCES engagement.audits(id),
    risk_code   VARCHAR(20) NOT NULL,
    probability SMALLINT NOT NULL CHECK (probability BETWEEN 1 AND 5),
    impact      SMALLINT NOT NULL CHECK (impact BETWEEN 1 AND 5),
    reason      TEXT NOT NULL,
    updated_by  UUID NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (audit_id, risk_code)
);
CREATE TABLE IF NOT EXISTS engagement.app_maturity (
    audit_id   UUID NOT NULL REFERENCES engagement.audits(id),
    domain_key VARCHAR(20) NOT NULL,
    level      SMALLINT NOT NULL CHECK (level BETWEEN 0 AND 5),
    note       TEXT,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (audit_id, domain_key)
);

-- Encuestas direccionadas recibidas (una por área y carga): quién respondió y qué archivo se aplicó.
CREATE TABLE IF NOT EXISTS engagement.app_surveys (
    id              UUID PRIMARY KEY,
    audit_id        UUID NOT NULL REFERENCES engagement.audits(id),
    area            VARCHAR(20) NOT NULL,
    respondent_name VARCHAR(160),
    respondent_role VARCHAR(160),
    answered_on     DATE,
    filename        TEXT NOT NULL,
    sha256          CHAR(64) NOT NULL,
    rows_applied    INTEGER NOT NULL DEFAULT 0,
    evidence_id     UUID REFERENCES engagement.evidence(id),
    imported_by     UUID NOT NULL,
    imported_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_surveys_audit_idx ON engagement.app_surveys (audit_id, area);

-- Catálogo normativo único (editable por Contraloría).
CREATE TABLE IF NOT EXISTS engagement.norms (
    code       VARCHAR(40) PRIMARY KEY,
    source     VARCHAR(12) NOT NULL CHECK (source IN ('ISO27001', 'COBIT', 'LEY_VE', 'SUDEASEG', 'CIS')),
    reference  TEXT NOT NULL,
    title      TEXT NOT NULL,
    summary    TEXT,
    status     VARCHAR(12) NOT NULL DEFAULT 'VIGENTE' CHECK (status IN ('VIGENTE', 'POR_VALIDAR', 'DEROGADA')),
    updated_by UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hallazgo automático descartado por el auditor (queda fuera de los listados, con su motivo).
ALTER TABLE engagement.observations ADD COLUMN IF NOT EXISTS discarded_by UUID;
ALTER TABLE engagement.observations ADD COLUMN IF NOT EXISTS discarded_at TIMESTAMPTZ;
ALTER TABLE engagement.observations ADD COLUMN IF NOT EXISTS discard_reason TEXT;
ALTER TABLE engagement.observations ADD COLUMN IF NOT EXISTS accepted_by UUID;
ALTER TABLE engagement.observations ADD COLUMN IF NOT EXISTS accepted_at TIMESTAMPTZ;

-- Retroalimentación del motor: solo inserción.
CREATE TABLE IF NOT EXISTS engagement.engine_feedback (
    id             BIGSERIAL PRIMARY KEY,
    audit_id       UUID REFERENCES engagement.audits(id),
    observation_id UUID REFERENCES engagement.observations(id),
    kind           VARCHAR(24) NOT NULL CHECK (kind IN ('OBS_ACCEPTED', 'OBS_EDITED', 'OBS_DISCARDED', 'RISK_CHANGED',
                                                         'CONCLUSION_REWRITTEN', 'RISK_MATRIX_OVERRIDE', 'MATURITY_OVERRIDE')),
    pattern_key    TEXT,
    controls       TEXT[],
    before         JSONB,
    after          JSONB,
    reason         TEXT,
    user_id        UUID NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS engine_feedback_pattern_idx ON engagement.engine_feedback (kind, pattern_key);

CREATE OR REPLACE FUNCTION engagement.engine_feedback_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'engine_feedback es de solo inserción';
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS engine_feedback_no_update ON engagement.engine_feedback;
CREATE TRIGGER engine_feedback_no_update BEFORE UPDATE OR DELETE ON engagement.engine_feedback
    FOR EACH ROW EXECUTE FUNCTION engagement.engine_feedback_append_only();

-- Propuestas del motor: nunca se aplican sin aprobación del Contralor.
CREATE TABLE IF NOT EXISTS engagement.rule_proposals (
    id            UUID PRIMARY KEY,
    kind          VARCHAR(10) NOT NULL CHECK (kind IN ('WEIGHT', 'RISK', 'RECOMMEND', 'SUPPRESS')),
    target        TEXT NOT NULL,
    value         JSONB NOT NULL,
    rationale     TEXT NOT NULL,
    evidence      JSONB NOT NULL DEFAULT '[]'::jsonb,
    status        VARCHAR(10) NOT NULL DEFAULT 'PROPUESTA' CHECK (status IN ('PROPUESTA', 'APROBADA', 'RECHAZADA', 'RETIRADA')),
    proposed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by    UUID,
    decided_at    TIMESTAMPTZ,
    decision_note TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS rule_proposals_open_idx ON engagement.rule_proposals (kind, target) WHERE status = 'PROPUESTA';

CREATE TABLE IF NOT EXISTS engagement.engine_rules (
    id          UUID PRIMARY KEY,
    kind        VARCHAR(10) NOT NULL CHECK (kind IN ('WEIGHT', 'RISK', 'RECOMMEND', 'SUPPRESS')),
    target      TEXT NOT NULL,
    value       JSONB NOT NULL,
    proposal_id UUID REFERENCES engagement.rule_proposals(id),
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    approved_by UUID NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_by  UUID,
    retired_at  TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS engine_rules_active_idx ON engagement.engine_rules (kind, target) WHERE active;

-- Catálogo normativo base (las referencias POR_VALIDAR las confirma el área legal).
INSERT INTO engagement.norms (code, source, reference, title, summary, status) VALUES
    ('ISO-A.5.3', 'ISO27001', 'Anexo A 5.3', 'Segregación de funciones', 'Las funciones y áreas de responsabilidad en conflicto deben segregarse.', 'VIGENTE'),
    ('ISO-A.5.15', 'ISO27001', 'Anexo A 5.15', 'Control de acceso', 'Reglas de control de acceso físico y lógico según requisitos de negocio y de seguridad.', 'VIGENTE'),
    ('ISO-A.5.16', 'ISO27001', 'Anexo A 5.16', 'Gestión de identidades', 'Ciclo de vida completo de las identidades, incluidas las cuentas técnicas.', 'VIGENTE'),
    ('ISO-A.5.17', 'ISO27001', 'Anexo A 5.17', 'Información de autenticación', 'Asignación y gestión controlada de contraseñas y demás información de autenticación.', 'VIGENTE'),
    ('ISO-A.5.18', 'ISO27001', 'Anexo A 5.18', 'Derechos de acceso', 'Provisión, revisión periódica, modificación y retiro de los derechos de acceso.', 'VIGENTE'),
    ('ISO-A.5.29', 'ISO27001', 'Anexo A 5.29', 'Seguridad durante una interrupción', 'Mantener la seguridad de la información durante una disrupción.', 'VIGENTE'),
    ('ISO-A.5.30', 'ISO27001', 'Anexo A 5.30', 'Preparación de las TIC para la continuidad', 'Planificar, implantar, mantener y probar la preparación de las TIC.', 'VIGENTE'),
    ('ISO-A.5.33', 'ISO27001', 'Anexo A 5.33', 'Protección de registros', 'Proteger los registros contra pérdida, destrucción, falsificación y acceso no autorizado.', 'VIGENTE'),
    ('ISO-A.5.34', 'ISO27001', 'Anexo A 5.34', 'Privacidad y protección de datos personales', 'Cumplir los requisitos legales sobre privacidad y datos personales.', 'VIGENTE'),
    ('ISO-A.8.2', 'ISO27001', 'Anexo A 8.2', 'Derechos de acceso privilegiado', 'Restringir y gestionar la asignación y uso de privilegios.', 'VIGENTE'),
    ('ISO-A.8.4', 'ISO27001', 'Anexo A 8.4', 'Acceso al código fuente', 'Gestionar adecuadamente el acceso de lectura y escritura al código fuente.', 'VIGENTE'),
    ('ISO-A.8.5', 'ISO27001', 'Anexo A 8.5', 'Autenticación segura', 'Tecnologías y procedimientos de autenticación segura según las restricciones de acceso.', 'VIGENTE'),
    ('ISO-A.8.6', 'ISO27001', 'Anexo A 8.6', 'Gestión de la capacidad', 'Monitorear y ajustar el uso de recursos según la capacidad requerida.', 'VIGENTE'),
    ('ISO-A.8.7', 'ISO27001', 'Anexo A 8.7', 'Protección contra malware', 'Protección contra software malicioso, incluido ransomware.', 'VIGENTE'),
    ('ISO-A.8.8', 'ISO27001', 'Anexo A 8.8', 'Gestión de vulnerabilidades técnicas', 'Obtener información de vulnerabilidades, evaluar la exposición y tomar medidas.', 'VIGENTE'),
    ('ISO-A.8.9', 'ISO27001', 'Anexo A 8.9', 'Gestión de la configuración', 'Establecer, documentar, implantar, monitorear y revisar configuraciones seguras.', 'VIGENTE'),
    ('ISO-A.8.11', 'ISO27001', 'Anexo A 8.11', 'Enmascaramiento de datos', 'Enmascarar datos según la política de control de acceso y los requisitos legales.', 'VIGENTE'),
    ('ISO-A.8.13', 'ISO27001', 'Anexo A 8.13', 'Respaldo de la información', 'Copias de respaldo mantenidas y probadas regularmente según la política acordada.', 'VIGENTE'),
    ('ISO-A.8.15', 'ISO27001', 'Anexo A 8.15', 'Registro de eventos', 'Producir, almacenar, proteger y analizar registros de actividades, excepciones y fallas.', 'VIGENTE'),
    ('ISO-A.8.16', 'ISO27001', 'Anexo A 8.16', 'Actividades de monitoreo', 'Monitorear redes, sistemas y aplicaciones para detectar comportamientos anómalos.', 'VIGENTE'),
    ('ISO-A.8.20', 'ISO27001', 'Anexo A 8.20', 'Seguridad de redes', 'Proteger las redes y dispositivos de red, y la información en sistemas y aplicaciones.', 'VIGENTE'),
    ('ISO-A.8.24', 'ISO27001', 'Anexo A 8.24', 'Uso de criptografía', 'Reglas para el uso efectivo de la criptografía, incluida la gestión de llaves.', 'VIGENTE'),
    ('ISO-A.8.25', 'ISO27001', 'Anexo A 8.25', 'Ciclo de vida de desarrollo seguro', 'Reglas para el desarrollo seguro de software y sistemas.', 'VIGENTE'),
    ('ISO-A.8.28', 'ISO27001', 'Anexo A 8.28', 'Codificación segura', 'Principios de codificación segura aplicados al desarrollo de software.', 'VIGENTE'),
    ('ISO-A.8.29', 'ISO27001', 'Anexo A 8.29', 'Pruebas de seguridad en desarrollo y aceptación', 'Procesos de pruebas de seguridad definidos e implantados en el ciclo de desarrollo.', 'VIGENTE'),
    ('ISO-A.8.31', 'ISO27001', 'Anexo A 8.31', 'Separación de ambientes', 'Separar y proteger los ambientes de desarrollo, pruebas y producción.', 'VIGENTE'),
    ('ISO-A.8.32', 'ISO27001', 'Anexo A 8.32', 'Gestión de cambios', 'Los cambios en las instalaciones y sistemas se someten a procedimientos de gestión de cambios.', 'VIGENTE'),
    ('ISO-A.8.33', 'ISO27001', 'Anexo A 8.33', 'Información de prueba', 'Seleccionar, proteger y gestionar adecuadamente la información de prueba.', 'VIGENTE'),
    ('COBIT-DSS04', 'COBIT', 'DSS04', 'Gestionar la continuidad', 'Plan de continuidad del negocio y de TI, con pruebas periódicas.', 'VIGENTE'),
    ('COBIT-DSS04.07', 'COBIT', 'DSS04.07', 'Gestionar los respaldos', 'Respaldos de sistemas, aplicaciones y datos según los requisitos de negocio.', 'VIGENTE'),
    ('COBIT-DSS05.02', 'COBIT', 'DSS05.02', 'Gestionar la seguridad de la red y las conexiones', 'Medidas de seguridad para proteger la información en todos los métodos de conexión.', 'VIGENTE'),
    ('COBIT-DSS05.04', 'COBIT', 'DSS05.04', 'Gestionar la identidad y el acceso lógico', 'Los usuarios tienen derechos de acceso según sus necesidades de negocio.', 'VIGENTE'),
    ('COBIT-DSS05.07', 'COBIT', 'DSS05.07', 'Gestionar la vigilancia de la infraestructura', 'Registro y monitoreo de eventos de seguridad.', 'VIGENTE'),
    ('COBIT-DSS06.02', 'COBIT', 'DSS06.02', 'Controlar el procesamiento de la información', 'Integridad, exactitud y validez del procesamiento de las transacciones.', 'VIGENTE'),
    ('COBIT-BAI06', 'COBIT', 'BAI06', 'Gestionar los cambios de TI', 'Cambios autorizados, probados y documentados de forma controlada.', 'VIGENTE'),
    ('COBIT-BAI07', 'COBIT', 'BAI07', 'Gestionar la aceptación y la transición del cambio', 'Aceptación formal por el negocio y transición controlada a producción.', 'VIGENTE'),
    ('COBIT-MEA03', 'COBIT', 'MEA03', 'Gestionar el cumplimiento de requisitos externos', 'Cumplimiento de leyes, regulaciones y requisitos contractuales.', 'VIGENTE'),
    ('VE-CRBV-28', 'LEY_VE', 'Constitución, art. 28', 'Habeas data', 'Derecho de toda persona a acceder a sus datos y a exigir su protección, actualización o rectificación. Venezuela no tiene una ley general de protección de datos.', 'VIGENTE'),
    ('VE-LAA', 'LEY_VE', 'Ley de la Actividad Aseguradora', 'Control interno de la actividad aseguradora', 'Obligaciones de control interno, registro y supervisión de las empresas de seguros.', 'POR_VALIDAR'),
    ('VE-LMDFE', 'LEY_VE', 'Decreto-Ley de Mensajes de Datos y Firmas Electrónicas', 'Eficacia de mensajes de datos y firma electrónica', 'Valor probatorio de los mensajes de datos y requisitos de la firma electrónica certificada (SUSCERTE).', 'VIGENTE'),
    ('VE-LEDI', 'LEY_VE', 'Ley Especial contra los Delitos Informáticos', 'Delitos contra sistemas de información', 'Tipifica el acceso indebido, el sabotaje y la violación de la privacidad de datos.', 'VIGENTE'),
    ('VE-INFOGOB', 'LEY_VE', 'Ley de Infogobierno', 'Seguridad de la información en el uso de TIC', 'Principios de seguridad e interoperabilidad de las tecnologías de información.', 'VIGENTE'),
    ('VE-LOCDOFT', 'LEY_VE', 'Ley Orgánica contra la Delincuencia Organizada y Financiamiento al Terrorismo', 'Prevención LC/FT/FPADM', 'Deberes de prevención y reporte de los sujetos obligados.', 'VIGENTE'),
    ('SUDEASEG-ELECTRONICO', 'SUDEASEG', 'Normas de trámites y procedimientos por medios electrónicos (G.O. Ext. 6.835 del 03/09/2024)', 'Medios electrónicos y seguridad de la información', 'Define la seguridad de la información (confidencialidad, integridad, privacidad y disponibilidad) en los trámites electrónicos.', 'VIGENTE'),
    ('SUDEASEG-LCFT', 'SUDEASEG', 'Providencia SAA-01-0536-2024', 'Administración de riesgos LC/FT/FPADM', 'Sistema integral de administración de riesgos de legitimación de capitales.', 'VIGENTE'),
    ('SUDEASEG-TI', 'SUDEASEG', 'Normas SUDEASEG sobre tecnología de la información (según matriz de Contraloría)', 'Pistas de auditoría inalterables', 'Mecanismos de audit trail que registren el ciclo de vida completo de cada transacción.', 'POR_VALIDAR'),
    ('SUDEASEG-CAMBIOS', 'SUDEASEG', 'Normas sobre control de cambios en sistemas aplicativos (según matriz de Contraloría)', 'Control de cambios', 'Ambientes segregados QA/producción con autorización formal (RFC) y pruebas.', 'POR_VALIDAR'),
    ('SUDEASEG-CONTINUIDAD', 'SUDEASEG', 'Lineamientos de BCP/DRP y riesgo operacional (según matriz de Contraloría)', 'Continuidad de los sistemas misionales', 'Respaldos periódicos y pruebas formales de recuperación ante desastres.', 'POR_VALIDAR'),
    ('SUDEASEG-RESERVAS', 'SUDEASEG', 'Providencias sobre notas técnicas y reservas técnicas', 'Parámetros actuariales', 'El software aplica fielmente las fórmulas actuariales de las notas técnicas aprobadas.', 'POR_VALIDAR'),
    ('SUDEASEG-CONTABLE', 'SUDEASEG', 'Normativa contable SUDEASEG y presentación de balances', 'Integridad financiera', 'Cuadre, conciliación periódica y prohibición de asientos manuales no justificados.', 'POR_VALIDAR'),
    ('SUDEASEG-INTERMEDIARIOS', 'SUDEASEG', 'Régimen de autorización de intermediarios de seguros', 'Intermediarios autorizados', 'Solo se opera con intermediarios cuya autorización esté vigente.', 'POR_VALIDAR')
ON CONFLICT (code) DO NOTHING;

GRANT SELECT, INSERT, UPDATE ON engagement.applications, engagement.app_tests, engagement.app_risk_overrides,
    engagement.app_maturity, engagement.norms, engagement.rule_proposals, engagement.engine_rules TO app_rw;
GRANT SELECT, INSERT ON engagement.app_surveys, engagement.engine_feedback TO app_rw;
GRANT USAGE ON SEQUENCE engagement.engine_feedback_id_seq TO app_rw;
