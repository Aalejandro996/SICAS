-- 030: tipos de auditoría (operativa, especial, administrativa y financiera), cédulas base de
-- cuentas por pagar, cuentas por cobrar y gestión administrativa, y catálogo normativo SUDEASEG.
-- Las cédulas son una BASE PROPUESTA para revisión de Contraloría (versión 1).

ALTER TABLE engagement.audits ADD COLUMN IF NOT EXISTS audit_kind VARCHAR(14);
UPDATE engagement.audits a SET audit_kind = CASE
        WHEN a.audit_domain = 'SISTEMAS' THEN 'SISTEMAS'
        WHEN u.kind = 'SUCURSAL' THEN 'OPERATIVA'
        ELSE 'ESPECIAL' END
FROM engagement.files f JOIN engagement.units u ON u.id = f.unit_id
WHERE f.id = a.file_id AND a.audit_kind IS NULL;
ALTER TABLE engagement.audits ALTER COLUMN audit_kind SET NOT NULL;
ALTER TABLE engagement.audits ADD CONSTRAINT audits_audit_kind_check
    CHECK (audit_kind IN ('SISTEMAS', 'OPERATIVA', 'ESPECIAL', 'ADMINISTRATIVA', 'FINANCIERA'));

-- Cédulas sin línea de negocio (línea GENERAL).
ALTER TABLE engagement.worksheets DROP CONSTRAINT IF EXISTS worksheets_kind_check;
ALTER TABLE engagement.worksheets DROP CONSTRAINT IF EXISTS worksheets_line_check;
ALTER TABLE engagement.worksheets ADD CONSTRAINT worksheets_kind_check
    CHECK (kind IN ('SUSCRIPCION', 'RECLAMO', 'SISTEMAS', 'CXP', 'CXC', 'ADMIN'));
ALTER TABLE engagement.worksheets ADD CONSTRAINT worksheets_line_check
    CHECK (line IN ('AUTO', 'PATRIMONIAL', 'PERSONAL', 'ERP_TI', 'GENERAL'));

DO $$
DECLARE c RECORD;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'engagement.financial_templates'::regclass AND contype = 'c'
             AND pg_get_constraintdef(oid) LIKE '%TRANSVERSAL%'
  LOOP
    EXECUTE format('ALTER TABLE engagement.financial_templates DROP CONSTRAINT %I', c.conname);
  END LOOP;
END $$;
ALTER TABLE engagement.financial_templates ADD CONSTRAINT financial_templates_kind_line_check CHECK (
    (kind = 'TRANSVERSAL' AND line IS NULL)
    OR (kind IN ('SUSCRIPCION', 'RECLAMO') AND line IN ('AUTO', 'PATRIMONIAL', 'PERSONAL'))
    OR (kind IN ('CXP', 'CXC', 'ADMIN') AND line = 'GENERAL'));

INSERT INTO engagement.financial_templates (code, domain, kind, line, title, source_file, source_sheet, source_sha256, version, active) VALUES ('AUD_CXP', 'FINANCIERA', 'CXP', 'GENERAL', 'Cuentas por pagar', 'Base propuesta SICAS v1 (pendiente de validación por Contraloría)', 'Cuentas por pagar', 'e2e713595cc95d8aa46ff78c0e54e0d2c6d96b4f8bf3ee964097480499f5094f', 1, TRUE) ON CONFLICT (code) DO NOTHING;
INSERT INTO engagement.financial_criteria (template_code, source_id, section, subsection, criterion_text, sort_order, excel_row) VALUES
    ('AUD_CXP', 'CXP-01', 'Soportes y registro', NULL, 'Verificar que cada cuenta por pagar registrada cuente con factura o documento soporte que cumpla los requisitos de facturación del SENIAT.', 1, 1),
    ('AUD_CXP', 'CXP-02', 'Soportes y registro', NULL, 'Verificar que las cuentas por pagar estén registradas en las cuentas del Código de Cuentas (Manual de Contabilidad) de la SUDEASEG que correspondan a su naturaleza.', 2, 2),
    ('AUD_CXP', 'CXP-03', 'Soportes y registro', NULL, 'Verificar que el auxiliar de cuentas por pagar concilie con el saldo del mayor contable al cierre del período y que las diferencias estén justificadas.', 3, 3),
    ('AUD_CXP', 'CXP-04', 'Aprobación y pago', NULL, 'Validar que cada pago cuente con orden de pago aprobada conforme al registro de firmas autorizadas y a los límites de aprobación vigentes.', 4, 4),
    ('AUD_CXP', 'CXP-05', 'Aprobación y pago', NULL, 'Verificar que no existan pagos duplicados ni pagos a proveedores no registrados en el maestro de proveedores.', 5, 5),
    ('AUD_CXP', 'CXP-06', 'Aprobación y pago', NULL, 'Verificar la segregación de funciones entre quien registra, quien aprueba y quien ejecuta los pagos.', 6, 6),
    ('AUD_CXP', 'CXP-07', 'Antigüedad y obligaciones con terceros', NULL, 'Validar la antigüedad de saldos e identificar partidas vencidas sin gestión de pago o sin justificación documentada.', 7, 7),
    ('AUD_CXP', 'CXP-08', 'Antigüedad y obligaciones con terceros', NULL, 'Verificar que las obligaciones con asegurados, beneficiarios, intermediarios y reaseguradores (siniestros, comisiones y primas por pagar) se registren y paguen en los plazos establecidos.', 8, 8),
    ('AUD_CXP', 'CXP-09', 'Impuestos y proveedores', NULL, 'Verificar que las retenciones de IVA e ISLR aplicadas a proveedores se calcularon, enteraron y declararon en los plazos legales.', 9, 9),
    ('AUD_CXP', 'CXP-10', 'Impuestos y proveedores', NULL, 'Verificar que los proveedores tengan expediente actualizado (RIF vigente, datos bancarios y debida diligencia conforme a la política de prevención de LC/FT).', 10, 10)
ON CONFLICT DO NOTHING;

INSERT INTO engagement.financial_templates (code, domain, kind, line, title, source_file, source_sheet, source_sha256, version, active) VALUES ('AUD_CXC', 'FINANCIERA', 'CXC', 'GENERAL', 'Cuentas por cobrar', 'Base propuesta SICAS v1 (pendiente de validación por Contraloría)', 'Cuentas por cobrar', 'f4c0ceb2b81fbb841b0427808359d2998dea99518d29735b2546086167b39909', 1, TRUE) ON CONFLICT (code) DO NOTHING;
INSERT INTO engagement.financial_criteria (template_code, source_id, section, subsection, criterion_text, sort_order, excel_row) VALUES
    ('AUD_CXC', 'CXC-01', 'Primas por cobrar', NULL, 'Verificar que las primas por cobrar registradas correspondan a pólizas emitidas y vigentes en el sistema de emisión.', 1, 1),
    ('AUD_CXC', 'CXC-02', 'Primas por cobrar', NULL, 'Validar la antigüedad de las primas por cobrar y el tratamiento de las primas pendientes de cobro y su anulación conforme a la normativa de la SUDEASEG.', 2, 2),
    ('AUD_CXC', 'CXC-03', 'Primas por cobrar', NULL, 'Verificar la constitución de la provisión para cuentas de cobro dudoso conforme a las normas contables aplicables a las empresas de seguros.', 3, 3),
    ('AUD_CXC', 'CXC-04', 'Conciliación y registro', NULL, 'Verificar que el auxiliar de cuentas por cobrar concilie con el mayor contable y que las partidas en conciliación estén justificadas.', 4, 4),
    ('AUD_CXC', 'CXC-05', 'Conciliación y registro', NULL, 'Verificar que las cuentas por cobrar a intermediarios, reaseguradores y otras empresas estén soportadas, confirmadas y conciliadas.', 5, 5),
    ('AUD_CXC', 'CXC-06', 'Cobranza', NULL, 'Verificar que los cobros recibidos se apliquen oportunamente a la cuenta del cliente y se depositen íntegramente en las cuentas de la empresa.', 6, 6),
    ('AUD_CXC', 'CXC-07', 'Cobranza', NULL, 'Verificar la gestión de cobranza (seguimiento, comunicaciones al cliente y responsables asignados).', 7, 7),
    ('AUD_CXC', 'CXC-08', 'Cobranza', NULL, 'Validar que los recibos de cobro y las facturas emitidas cumplan los requisitos del SENIAT.', 8, 8),
    ('AUD_CXC', 'CXC-09', 'Ajustes y control', NULL, 'Verificar que los ajustes, notas de crédito y castigos de cuentas por cobrar estén autorizados y documentados.', 9, 9),
    ('AUD_CXC', 'CXC-10', 'Ajustes y control', NULL, 'Verificar la segregación de funciones entre emisión, cobro y registro contable.', 10, 10)
ON CONFLICT DO NOTHING;

INSERT INTO engagement.financial_templates (code, domain, kind, line, title, source_file, source_sheet, source_sha256, version, active) VALUES ('AUD_ADMIN', 'FINANCIERA', 'ADMIN', 'GENERAL', 'Gestión administrativa', 'Base propuesta SICAS v1 (pendiente de validación por Contraloría)', 'Gestión administrativa', '47644940b531a75541be91d58a1548bcd596fd967b6e2f6f86f0a424c3294a30', 1, TRUE) ON CONFLICT (code) DO NOTHING;
INSERT INTO engagement.financial_criteria (template_code, source_id, section, subsection, criterion_text, sort_order, excel_row) VALUES
    ('AUD_ADMIN', 'ADMIN-01', 'Gobierno de la unidad', NULL, 'Verificar que la unidad cuente con manual de normas y procedimientos aprobado, vigente y divulgado al personal.', 1, 1),
    ('AUD_ADMIN', 'ADMIN-02', 'Gobierno de la unidad', NULL, 'Verificar que la estructura organizativa y las descripciones de cargo estén aprobadas y actualizadas.', 2, 2),
    ('AUD_ADMIN', 'ADMIN-03', 'Gobierno de la unidad', NULL, 'Validar la existencia y vigencia del registro de firmas autorizadas y de los niveles de aprobación de la unidad.', 3, 3),
    ('AUD_ADMIN', 'ADMIN-04', 'Gestión documental y activos', NULL, 'Verificar el control de documentos y el archivo físico y digital de la unidad, con criterios de conservación y confidencialidad.', 4, 4),
    ('AUD_ADMIN', 'ADMIN-05', 'Gestión documental y activos', NULL, 'Verificar la custodia de los activos asignados a la unidad y la conciliación de su inventario.', 5, 5),
    ('AUD_ADMIN', 'ADMIN-06', 'Gastos y compras', NULL, 'Verificar que los gastos y compras de la unidad estén soportados, autorizados y dentro del presupuesto aprobado.', 6, 6),
    ('AUD_ADMIN', 'ADMIN-07', 'Cumplimiento', NULL, 'Verificar la atención, dentro de los plazos, de los requerimientos de la SUDEASEG y de otros entes reguladores.', 7, 7),
    ('AUD_ADMIN', 'ADMIN-08', 'Cumplimiento', NULL, 'Verificar el cumplimiento de los planes de acción correctiva de auditorías anteriores.', 8, 8),
    ('AUD_ADMIN', 'ADMIN-09', 'Cumplimiento', NULL, 'Verificar la aplicación de la política de prevención de LC/FT/FPADM en los procesos de la unidad que lo requieran.', 9, 9),
    ('AUD_ADMIN', 'ADMIN-10', 'Control interno', NULL, 'Verificar la segregación de funciones en los procesos críticos de la unidad.', 10, 10)
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------- catálogo normativo SUDEASEG
-- El motor de reglas redacta criterio, causa, efecto y recomendación de cada hallazgo a partir de
-- este catálogo. Cita los instrumentos normativos por tema, sin números de artículo; Contraloría
-- puede editar los textos (y agregar artículos) desde SICAS.
CREATE TABLE IF NOT EXISTS engagement.regulatory_catalog (
    topic VARCHAR(30) PRIMARY KEY,
    label TEXT NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    criteria TEXT NOT NULL,
    cause TEXT NOT NULL,
    effect TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 100,
    updated_by UUID,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON engagement.regulatory_catalog TO app_rw;
INSERT INTO engagement.regulatory_catalog (topic, label, keywords, criteria, cause, effect, recommendation, sort_order) VALUES
    ('suscripcion', 'suscripción y emisión de pólizas', ARRAY['suscrip', 'expediente', 'planilla', 'solicitud', 'tomador', 'poliza', 'cobertura', 'emision', 'bien asegurable']::text[],
     'Ley de la Actividad Aseguradora y Normas que Regulan la Relación Contractual en la Actividad Aseguradora (SUDEASEG): requisitos de la solicitud de seguro, de la póliza y de la documentación del tomador y del bien asegurado.',
     'La sucursal no aplica de forma consistente el procedimiento de suscripción: la verificación de recaudos depende del funcionario, no existe una lista de chequeo obligatoria ni una revisión de calidad previa a la emisión.',
     'Pólizas emitidas sin los recaudos exigidos debilitan la posición de la empresa ante reclamos, dificultan la defensa en procedimientos administrativos y exponen a observaciones y sanciones de la SUDEASEG por incumplimiento de las normas contractuales.',
     'Aplicar una lista de chequeo obligatoria de recaudos en la suscripción, con revisión de un segundo funcionario antes de la emisión, completar los expedientes observados y capacitar al personal de la sucursal en las normas contractuales vigentes.', 10),
    ('siniestros', 'atención de reclamos y pago de indemnizaciones', ARRAY['reclamo', 'siniestro', 'indemniz', 'finiquito', 'liquidac', 'ajuste', 'beneficiario']::text[],
     'Ley de la Actividad Aseguradora y Normas que Regulan la Relación Contractual en la Actividad Aseguradora (SUDEASEG): notificación del siniestro, recaudos, ajuste, plazos de pago e indemnización; normas prudenciales sobre la reserva de siniestros pendientes.',
     'El trámite de reclamos no tiene controles formales de recaudos, plazos y aprobación por niveles; el seguimiento de cada caso depende de registros manuales.',
     'Indemnizaciones pagadas sin soporte o fuera de plazo generan riesgo de fraude, pagos indebidos, reclamos de asegurados, sanciones de la SUDEASEG y errores en la reserva de siniestros pendientes.',
     'Formalizar la lista de recaudos y los niveles de aprobación de indemnizaciones, controlar los plazos de respuesta y pago con alertas, y revisar mensualmente una muestra de expedientes pagados.', 20),
    ('lcft', 'prevención de legitimación de capitales (conozca a su cliente)', ARRAY['identificac', 'debida diligencia', 'rif', 'cedula', 'c.i', 'huella', 'verificacion de datos', 'origen de fondos', 'conozca', 'lc/ft', 'legitimacion']::text[],
     'Normas sobre Administración y Fiscalización de los Riesgos de Legitimación de Capitales, Financiamiento al Terrorismo y Financiamiento de la Proliferación de Armas de Destrucción Masiva (SUDEASEG) y Ley Orgánica contra la Delincuencia Organizada y Financiamiento al Terrorismo: identificación, verificación y debida diligencia del cliente.',
     'La política de conozca a su cliente no se aplica de forma completa en la sucursal: faltan controles que impidan emitir o pagar sin los datos y documentos de identificación exigidos.',
     'Operar con clientes no identificados o sin debida diligencia expone a la empresa a ser utilizada para legitimar capitales, a sanciones de la SUDEASEG y a responsabilidad penal y reputacional.',
     'Bloquear en el sistema la emisión y el pago sin los datos y documentos de identificación obligatorios, completar la debida diligencia de los clientes observados y reforzar la capacitación del personal en prevención de LC/FT/FPADM.', 30),
    ('pagos', 'egresos, pagos y cuentas por pagar', ARRAY['pago', 'egreso', 'factura', 'proveedor', 'orden de pago', 'comision', 'cuentas por pagar', 'obligacion', 'retencion', 'ads']::text[],
     'Manual de Contabilidad y Código de Cuentas para las Empresas de Seguros (SUDEASEG); normas prudenciales y de control interno dictadas por la SUDEASEG; Código Orgánico Tributario y providencias del SENIAT sobre facturación y retenciones.',
     'Los pagos no se someten a una verificación sistemática de soportes, aprobación por firmas autorizadas y conciliación con los registros contables; las funciones de registro, aprobación y pago no están suficientemente separadas.',
     'Pagos sin soporte o mal registrados pueden ocultar fraudes, pagos duplicados o indebidos, distorsionan los estados financieros presentados a la SUDEASEG y generan contingencias fiscales por retenciones no enteradas.',
     'Exigir orden de pago aprobada según el registro de firmas autorizadas con todos los soportes, conciliar mensualmente el auxiliar con el mayor, separar las funciones de registro, aprobación y pago, y depurar las partidas vencidas.', 40),
    ('cobranza', 'primas y cuentas por cobrar', ARRAY['prima', 'cobr', 'cuentas por cobrar', 'provision', 'anulac', 'recibo', 'nota de credito', 'castigo']::text[],
     'Manual de Contabilidad y Código de Cuentas para las Empresas de Seguros (SUDEASEG): registro de primas y cuentas por cobrar y su provisión; normas de la SUDEASEG sobre primas pendientes de cobro.',
     'La gestión de cobranza y la conciliación de cuentas por cobrar no siguen un procedimiento formal con responsables, plazos y revisión periódica de antigüedad.',
     'Saldos por cobrar no conciliados o sin provisión sobrestiman los activos y los resultados reportados a la SUDEASEG, y las primas no cobradas mantienen coberturas sin contraprestación.',
     'Conciliar mensualmente el auxiliar de cuentas por cobrar con el mayor, analizar la antigüedad de saldos, constituir las provisiones correspondientes y documentar la gestión de cobranza y las anulaciones autorizadas.', 50),
    ('fiscal', 'obligaciones fiscales y municipales', ARRAY['cartelera', 'fiscal', 'impuesto', 'islr', 'iva', 'seniat', 'municipal', 'declaracion']::text[],
     'Código Orgánico Tributario, Ley de Impuesto sobre la Renta, Ley de Impuesto al Valor Agregado y providencias del SENIAT; ordenanzas municipales sobre actividades económicas.',
     'La sucursal no tiene asignado un responsable ni un calendario de control de sus obligaciones fiscales y municipales y de la documentación que debe exhibir.',
     'El incumplimiento de obligaciones fiscales y municipales puede generar multas, cierres temporales del establecimiento y daño a la imagen de la empresa.',
     'Asignar un responsable de las obligaciones fiscales y municipales de la sucursal, mantener un calendario de vencimientos y verificar mensualmente la documentación exhibida y las declaraciones presentadas.', 60),
    ('gobierno', 'gobierno, procedimientos y control interno', ARRAY['manual', 'procedimiento', 'estructura', 'cargo', 'firmas autorizadas', 'archivo', 'activo', 'presupuesto', 'requerimiento', 'plan de accion', 'segregacion', 'normas']::text[],
     'Ley de la Actividad Aseguradora (deberes de la junta directiva y sistema de control interno) y normas prudenciales y de control interno dictadas por la SUDEASEG; marco COSO 2013 como referencia de control interno.',
     'La unidad no ha formalizado o actualizado sus normas, procedimientos, responsables y niveles de aprobación, y no hay seguimiento periódico de su cumplimiento.',
     'La falta de procedimientos y controles formales aumenta el riesgo de errores, fraudes e incumplimientos regulatorios, y dificulta atender los requerimientos de la SUDEASEG.',
     'Formalizar y aprobar los procedimientos de la unidad, actualizar el registro de firmas autorizadas y las descripciones de cargo, asignar responsables de seguimiento y verificar trimestralmente el cumplimiento de los planes de acción.', 70),
    ('general', 'control interno de la operación', '{}'::text[],
     'Ley de la Actividad Aseguradora y normas prudenciales y de control interno dictadas por la SUDEASEG.',
     'El control evaluado no está formalizado en un procedimiento con responsables, evidencia de ejecución y supervisión.',
     'La ausencia o debilidad del control expone a la empresa a errores, fraudes e incumplimientos regulatorios con posibles sanciones de la SUDEASEG.',
     'Formalizar el control en un procedimiento aprobado, asignar su responsable, conservar evidencia de su ejecución y supervisar periódicamente su cumplimiento.', 999)
ON CONFLICT (topic) DO NOTHING;

-- Clave de la regla que originó una observación automática (evita duplicarla al regenerar).
ALTER TABLE engagement.observations ADD COLUMN IF NOT EXISTS rule_key TEXT;
