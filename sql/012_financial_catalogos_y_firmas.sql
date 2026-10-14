-- 011: Catalogos financieros, sucursales activas y perfiles de firmas visuales.
-- PASO 1: SOLO ADITIVO.
-- NO modifica tablas ni logica de Auditoria de Sistemas.
-- NO toca la carpeta secrets ni material criptografico.
BEGIN;

CREATE TABLE IF NOT EXISTS engagement.financial_templates (
    code VARCHAR(40) PRIMARY KEY,
    domain VARCHAR(12) NOT NULL DEFAULT 'FINANCIERA'
        CHECK (domain = 'FINANCIERA'),
    kind VARCHAR(20) NOT NULL
        CHECK (kind IN ('TRANSVERSAL','SUSCRIPCION','RECLAMO')),
    line VARCHAR(12),
    title TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    version INT NOT NULL DEFAULT 1 CHECK (version >= 1),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (kind = 'TRANSVERSAL' AND line IS NULL)
        OR
        (kind IN ('SUSCRIPCION','RECLAMO') AND line IN ('AUTO','PATRIMONIAL','PERSONAL'))
    )
);

CREATE TABLE IF NOT EXISTS engagement.financial_criteria (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_code VARCHAR(40) NOT NULL
        REFERENCES engagement.financial_templates(code),
    source_id TEXT NOT NULL,
    section TEXT NOT NULL,
    subsection TEXT,
    criterion_text TEXT NOT NULL,
    sort_order INT NOT NULL CHECK (sort_order > 0),
    excel_row INT NOT NULL CHECK (excel_row > 0),
    weight NUMERIC(10,4),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (template_code, source_id),
    UNIQUE (template_code, sort_order)
);

CREATE INDEX IF NOT EXISTS idx_financial_criteria_template_order
    ON engagement.financial_criteria(template_code, sort_order);

CREATE TABLE IF NOT EXISTS engagement.signature_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL
        REFERENCES iam.users(id) ON DELETE RESTRICT,
    signature_type VARCHAR(16) NOT NULL
        CHECK (signature_type IN ('COMPLETA','MEDIA')),
    original_filename TEXT NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    width_px INT CHECK (width_px > 0),
    height_px INT CHECK (height_px > 0),
    sha256 CHAR(64) NOT NULL,
    content BYTEA NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES iam.users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_signature_asset_active
    ON engagement.signature_assets(user_id, signature_type)
    WHERE active;

CREATE INDEX IF NOT EXISTS idx_signature_assets_user
    ON engagement.signature_assets(user_id, signature_type, active);

-- Sucursales activas suministradas por Contraloria.
-- Conflictos de nombre/tipo NO se modifican.

INSERT INTO engagement.units (code,name,kind,active) VALUES
    ('100101','CARACAS','SUCURSAL',TRUE),
    ('100301','VARGAS','SUCURSAL',TRUE),
    ('100302','GUARENAS/GUATIRE','SUCURSAL',TRUE),
    ('100303','CHARALLAVE','SUCURSAL',TRUE),
    ('200501','VALENCIA','SUCURSAL',TRUE),
    ('200601','SAN CARLOS','SUCURSAL',TRUE),
    ('200702','CALABOZO','SUCURSAL',TRUE),
    ('301201','MERIDA','SUCURSAL',TRUE),
    ('301301','SAN CRISTOBAL','SUCURSAL',TRUE),
    ('301401','VALERA','SUCURSAL',TRUE),
    ('401201','VALLE DE LA PASCUA','SUCURSAL',TRUE),
    ('401501','MARACAY','SUCURSAL',TRUE),
    ('401701','BARINAS','SUCURSAL',TRUE),
    ('501801','PUERTO LA CRUZ','SUCURSAL',TRUE),
    ('501901','EL TIGRE','SUCURSAL',TRUE),
    ('502001','PORLAMAR','SUCURSAL',TRUE),
    ('502101','GUIRIA','SUCURSAL',TRUE),
    ('502201','CARUPANO','SUCURSAL',TRUE),
    ('502701','CUMANA','SUCURSAL',TRUE),
    ('602301','PUERTO ORDAZ','SUCURSAL',TRUE),
    ('602302','MATURIN','SUCURSAL',TRUE),
    ('702401','BARQUISIMETO','SUCURSAL',TRUE),
    ('702601','SAN FELIPE','SUCURSAL',TRUE),
    ('702701','ACARIGUA','SUCURSAL',TRUE),
    ('802501','MARACAIBO','SUCURSAL',TRUE) 
ON CONFLICT (code) DO UPDATE SET active = TRUE
WHERE engagement.units.kind = 'SUCURSAL'
  AND upper(engagement.units.name) = upper(EXCLUDED.name);


INSERT INTO engagement.financial_templates (code,domain,kind,line,title,source_file,source_sheet,source_sha256,version,active) VALUES
    ('FIN_TRANSVERSAL_CARTELERA','FINANCIERA','TRANSVERSAL',NULL,'Atributos Cartelera Fiscal / Firmas Autorizadas','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE),
    ('FIN_TRANSVERSAL_ADS','FINANCIERA','TRANSVERSAL',NULL,'Atributos Evaluación ADS','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE),
    ('FIN_AUTO_SUSCRIPCION','FINANCIERA','SUSCRIPCION','AUTO','Atributos AUTO Suscripción','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE),
    ('FIN_AUTO_RECLAMO','FINANCIERA','RECLAMO','AUTO','Atributos AUTO Indemnización','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE),
    ('FIN_PERSONAL_SUSCRIPCION','FINANCIERA','SUSCRIPCION','PERSONAL','Atributos Personas Suscripción','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE),
    ('FIN_PERSONAL_RECLAMO','FINANCIERA','RECLAMO','PERSONAL','Atributos Personas Indemnización','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE),
    ('FIN_PATRIMONIAL_RECLAMO','FINANCIERA','RECLAMO','PATRIMONIAL','Atributos Patrimonial Indemnización','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE),
    ('FIN_PATRIMONIAL_SUSCRIPCION','FINANCIERA','SUSCRIPCION','PATRIMONIAL','Atributos Suscripción Patrimonial','Atributos Auditorias.xlsx','Administración CF','d64ef5bedf01fe16bbabeee14aa7223a10a8851cca4414acdc36e7598c910c5a',1,TRUE) 
ON CONFLICT (code) DO UPDATE SET
    title=EXCLUDED.title,
    source_file=EXCLUDED.source_file,
    source_sheet=EXCLUDED.source_sheet,
    source_sha256=EXCLUDED.source_sha256,
    active=TRUE;


INSERT INTO engagement.financial_criteria (template_code,source_id,section,subsection,criterion_text,sort_order,excel_row) VALUES
    ('FIN_TRANSVERSAL_CARTELERA','AC-B.3.5.1','Atributos Cartelera Fiscal/ Firmas Autorizadas',NULL,'Validar que la Cartelera Fiscal este ubicada en la entrada de la sucursal en un lugar visible.',2,2),
    ('FIN_TRANSVERSAL_CARTELERA','AC-B.3.52','Atributos Cartelera Fiscal/ Firmas Autorizadas',NULL,'Verificar que la cartelera contenga la documentación,  con copia de los documentos obligatorios, minimos necesarios  y que estos esten legibles y vigentes.',3,3),
    ('FIN_TRANSVERSAL_CARTELERA','AC-B.3.5.3','Atributos Cartelera Fiscal/ Firmas Autorizadas',NULL,'Validar que las declaraciones de impuestos municipales esten al dia. (Se deben revisar las ultimas Tres (3) declaraciones).',4,4),
    ('FIN_TRANSVERSAL_CARTELERA','AC-B.3.5.4','Atributos Cartelera Fiscal/ Firmas Autorizadas',NULL,'Se efectuó  levantamiento de las firmas autorizadas de la Sucursal, ¿Resultó conforme?',5,5),
    ('FIN_TRANSVERSAL_ADS','AC-B.3.5.5','Atributos Evaluación ADS',NULL,'Verificar que la relación de egreso se encuentre firmada por el administrador y el ADS',8,8),
    ('FIN_TRANSVERSAL_ADS','AC-B.3.5.6','Atributos Evaluación ADS',NULL,'Validar que las facturas soportes del pago cumplan con la normativa establecida por el SENIAT y presenten el sello de pagado.',9,9),
    ('FIN_TRANSVERSAL_ADS','AC-B.3.5.7','Atributos Evaluación ADS',NULL,'Validar que el (monto, ADS y fecha del egreso) corresponda con los soportes presentados.',10,10),
    ('FIN_TRANSVERSAL_ADS','AC-B.3.5.8','Atributos Evaluación ADS',NULL,'Verificar que existan copias de los billetes incluyendo el vuelto y que los mismos esten firmados por el ADS',11,11),
    ('FIN_TRANSVERSAL_ADS','AC-B.3.5.9','Atributos Evaluación ADS',NULL,'Verificar que no existen diferencias en montos en la emisión del egreso vs  listado de comisiones.',12,12),
    ('FIN_TRANSVERSAL_ADS','AC-B.3.5.10','Atributos Evaluación ADS',NULL,'Verificar que la obligacion se encuentre con estatus de PAG a nivel de Sistema',13,13),
    ('FIN_TRANSVERSAL_ADS','AC-B.3.5.11','Atributos Evaluación ADS',NULL,'Verificar que los soportes solicitados sean entregados de manera satisfactoria',14,14),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.1','Atributos AUTO Suscripción',NULL,'Verificar que los Expedientes solicitados sean debidamente recibidos.',17,17),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.2','Atributos AUTO Suscripción',NULL,'Verificar que el expediente contenga la planilla de solicitud correspondiente, y el sello de recibido de la sucursal.',18,18),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.3','Atributos AUTO Suscripción',NULL,'Verificar que la planilla estè firmada (la misma debe corresponder con la C.I ) y huella dactilar del tomador y/o cliente',19,19),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.4','Atributos AUTO Suscripción',NULL,'Validar que los campos de datos personales del tomador y /o cliente se encuentren completados (nombre y apellido completos, C.I, RIF, dirección de residencia, domicilio, correo electrónico y datos telefónicos)',20,20),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.5','Atributos AUTO Suscripción',NULL,'Validar que los datos del bien asegurable, se encuentren completados (marca, modelo, año, color, serial de carrocería, serial del motor), e información respectivas coberturas amparadas.',21,21),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.6','Atributos AUTO Suscripción',NULL,'Verificar que los soportes se encuentren en el expediente digital o físico:  C.I y RIF vigente, Certificado de Origen o Título de Propieda del bien asegurable, identidad del conductor habitual vigentes (C.I, RIF, Carnet de Trabajo),  Referencia Bancaria, Declaración de ISLR y Constancia de Verificación de Datos.',22,22),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.7','Atributos AUTO Suscripción',NULL,'En caso de ausencia de soportes sobre el punto anterior, validar si existe un seguimiento efectivo de la gestiòn en Acselx. Mínimo 3 reseñas de recordatorio solicitando la documentaciòn.',23,23),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.8','Atributos AUTO Suscripción',NULL,'Validar que el vehículo asegurado se encuentre dentro del rango de vehículos aceptados para la suscripción',24,24),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.9','Atributos AUTO Suscripción',NULL,'Verificar que la información cargada en sistema, corresponde a lo reflejado en documentos del vehículo: marca, modelo, color, año, seriales del vehículo',25,25),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.10','Atributos AUTO Suscripción',NULL,'Validar que la suma asegurada del vehículo se corresponda al valor INMA en Sistema Acselx. En caso de ser un vehìculo 0K al monto de la factura proforma',26,26),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.11','Atributos AUTO Suscripción',NULL,'Verificar la existencia inspección física o digital del vehículo (si aplica por año/modelo). Fotos obligatorias: cuatro lados, seriales motor/carrocería, tablero y/o marcaje de kilometraje. Informe o valoración técnica del perito antes de emisión en Acselx',27,27),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.12','Atributos AUTO Suscripción',NULL,'Validar que el vehículo asegurado no presente daños, caso contrario, deben estar excluidos en anexos. (Soporte de anexos en fisico en expediente y registrados en Acselx)',28,28),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.13','Atributos AUTO Suscripción',NULL,'Verificar que las tasas aplicadas en suscripciones RCV, se aplique el cambio Referencial (TCR) vigente según SUDEASEG, Gaceta Oficial Extraordinaria Nº 6.835, publicada 3/9/2024',29,29),
    ('FIN_AUTO_SUSCRIPCION','AC-B.1.1.14','Atributos AUTO Suscripción',NULL,'Verificar y comprobar que exista el cobro de la prima en el sistema Acselx',30,30),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.1','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Validar que la solicitud de seguros se encuentre debidamente completada en todos sus campos, firmada y con la huella dactilar del solicitante, incluyendo la Declaraciòn Jurada de Origen de Fondos.',32,32),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.2','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar existencia de Contrato suscrito (Anexos, Condicionados). Validar la Identificación del Beneficiario Final.',33,33),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.3','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar Documentaciòn de identidad del solicitante: C.I o Pasaporte /  RIF y su debida  validaciòn en Portales WEB Pùblicos (CNE , SENIAT y/o SSO), a fines de comprobar su autenticidad.',34,34),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.4','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar que el expediente cuente con Referencias Bancarias, Ultima declaracion I.S.L.R.',35,35),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.5','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar existencias de Registro Mercantil / Documento Constitutivo / Acta  Asamblea  Accionistas (Modificaciones). Casos de Renovcaciones, debe existir Constancia de Actualizaciòn de Datos (frecuencia anual).',36,36),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.6','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar la debida diligencia cuando una Persona es Políticamente Expuesta.',37,37),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.7','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Validar el Soporte de Riesgo para las operaciones en Actividades y Profesiones No Financieras Designadas.',38,38),
    ('FIN_AUTO_SUSCRIPCION','AR\LC AUTO 1.8','Atributos AUTO Suscripción','AR-LC-FT-FPADM y otros ilícitos','Soporte de calificación de Riesgo efectuado por la UAR (Art 25, 26, 27).',39,39),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.1','Atributos AUTO Indemnización',NULL,'Verificar que los Expedientes solicitados sean debidamente recibidos.',43,43),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.2','Atributos AUTO Indemnización',NULL,'Verificar que el expediente de siniestro contenga la declaración formal elaborada por el Asegurado, debidamente llena en los campos requeridos y que se encuentre firmada por el Asegurado.',44,44),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.3','Atributos AUTO Indemnización',NULL,'Verificar que los reclamos sean notificados en los tiempos establecidos en las condiciones de la póliza.',45,45),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.4','Atributos AUTO Indemnización',NULL,'Validar que la documentación presente el sello de recibido por parte de la sucursal.',46,46),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.5','Atributos AUTO Indemnización',NULL,'Validar que el expediente contenga toda la Documentación inicial requerida. (Fisico o digital).',47,47),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.6','Atributos AUTO Indemnización',NULL,'Gestiones siniestros pendientes > 45 días.',48,48),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.7','Atributos AUTO Indemnización',NULL,'Verificar el respectivo seguimiento por parte de la sucursal.',49,49),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.8','Atributos AUTO Indemnización',NULL,'Verificar el adecuado registro en Sistema de las causas.',50,50),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.9','Atributos AUTO Indemnización',NULL,'Verificar que la cobertura afectada de la póliza sea la correcta así como el año póliza correspondiente.',51,51),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.10','Atributos AUTO Indemnización',NULL,'Validar que se realizó de forma adecuada y completa, el ajuste de daños, y cumple con el tipo de daño y piezas reclamadas.',52,52),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.11','Atributos AUTO Indemnización',NULL,'Valide que existan las fotos de rigor y adicionales del siniestro establecidas en la normativa (físicas o electrónicas) y que las mismas sean claras y suficientes.',53,53),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.12','Atributos AUTO Indemnización',NULL,'Validar que se haya realizado la notificación del siniestro a la Ofic. Ppal. a más tardar al día habil siguiente de recibido los soporte.',54,54),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.13','Atributos AUTO Indemnización',NULL,'Verificar que la constitución de reserva y el monto que se registren en Sistema estén acorde a los tiempos y parámetros establecidos en la Normativa.',55,55),
    ('FIN_AUTO_RECLAMO','AC-B.2.2.14','Atributos AUTO Indemnización',NULL,'Verificar que los siniestros sean pagados o rechazados dentro de los lapsos establecidos en la normativa.',56,56),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.1','Atributos Personas Suscripción',NULL,'Verificar que el Expediente requerido bajo muestra sea debidamente recibido.',59,59),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.2','Atributos Personas Suscripción',NULL,'Validar que la solicitud de seguros se presente completada en todas sus partes al momento de la emisión.(verificar con informacion cargada en Sistema AcselX).',60,60),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.3','Atributos Personas Suscripción',NULL,'Verificar Documentación del asegurado y/o contratante. (Nucleo familiar si aplica).',61,61),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.4','Atributos Personas Suscripción',NULL,'Existencia de Declaración de salud completa en todas sus partes, en caso de declarar una patología, emitir anexo de exclusión de cobertura (en caso que aplique).',62,62),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.5','Atributos Personas Suscripción',NULL,'Validar las Coberturas aplicadas a la pólizas  corresponden a las solicitadas por el asegurado.',63,63),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.6','Atributos Personas Suscripción',NULL,'Constatar que las personas aseguradas en la póliza son asegurables (riesgos permitidos) de acuerdo a las normas y políticas de suscripción de empresa (enfermedades declaradas, por resultados médicos o por historial de siniestralidad)',64,64),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.7','Atributos Personas Suscripción',NULL,'Verificar que la emision está acorde a las políticas de la compañia (continuidad, plazos de espera, Hijo o hermanos < a 25 años como y padres < 69, examenes medicos según la edad).',65,65),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.8','Atributos Personas Suscripción',NULL,'Validar la emisiòn de pòliza en el plazo correspondiente, de acuerdo a la fecha de solicitud. Plazo no mayor de 10 dias hàbiles de su recepciòn, acorde a GO Extraordinaria Nro. 6835 del 03/09/2024 y  Manual de Normas vigente.',66,66),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.9','Atributos Personas Suscripción',NULL,'Verificar que la vigencia se corresponda a las póliticas establecidas por la compañia.',67,67),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.10','Atributos Personas Suscripción',NULL,'Validar que los datos del asegurado y/o tomador de la póliza coinciden con registro en sistema (Nombre, apellido, C.I. telefono, correo, cuenta bancaria).',68,68),
    ('FIN_PERSONAL_SUSCRIPCION','AC-B.1.3.11','Atributos Personas Suscripción',NULL,'Verificar que el cobro de la prima se haya realizado en un maximo de 30 días continuos.',69,69),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.1','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','Validar que la solicitud de seguros se encuentre debidamente completada en todos sus campos, firmada y con la huella dactilar del solicitante, incluyendo la Declaraciòn Jurada de Origen de Fondos.',71,71),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.2','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar existencia de Contrato suscrito (Anexos, Condicionados). Validar la Identificación del Beneficiario Final.',72,72),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.3','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar Documentaciòn de identidad del solicitante: C.I o Pasaporte /  RIF y su debida  validaciòn en Portales WEB Pùblicos (CNE , SENIAT y/o SSO), a fines de comprobar su autenticidad.',73,73),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.4','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar que el expediente cuente con Referencias Bancarias, Ultima declaracion I.S.L.R.',74,74),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.5','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar existencias de Registro Mercantil / Documento Constitutivo / Acta  Asamblea  Accionistas (Modificaciones). Casos de Renovcaciones, debe existir Constancia de Actualizaciòn de Datos (frecuencia anual).',75,75),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.6','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','Verificar la debida diligencia cuando una Persona es Políticamente Expuesta.',76,76),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.7','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','Validar el Soporte de Riesgo para las operaciones en Actividades y Profesiones No Financieras Designadas.',77,77),
    ('FIN_PERSONAL_SUSCRIPCION','AR\LC PERSONAS 1.8','Atributos Personas Suscripción','AR-LC-FT-FPADM y otros ilícitos','"Soporte de calificación de Riesgo efectuado por la UAR (Art 25, 26, 27)."',78,78),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.1','Atributos Personas Indemnización',NULL,'Verificar que los Expedientes solicitados sean debidamente recibidos.',80,80),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.2','Atributos Personas Indemnización',NULL,'Verificar que el expediente de siniestro contenga la declaración formal elaborada por el Asegurado, debidamente llena en los campos requeridos y que se encuentre firmada por el Asegurado.',81,81),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.3','Atributos Personas Indemnización',NULL,'Verificar que los reclamos sean notificados en los tiempos establecidos en las condiciones de la póliza.',82,82),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.4','Atributos Personas Indemnización',NULL,'Validar que la documentación presente el sello de recibido por parte de la sucursal.',83,83),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.5','Atributos Personas Indemnización',NULL,'Validar que el expediente contenga toda la Documentación inicial requerida. (Fisico o digital).',84,84),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.6','Atributos Personas Indemnización',NULL,'Gestiones siniestros pendientes > 45 días.',85,85),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.7','Atributos Personas Indemnización',NULL,'Verificar el respectivo seguimiento por parte de la sucursal.',86,86),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.8','Atributos Personas Indemnización',NULL,'Verificar el adecuado registro en Sistema de las causas.',87,87),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.9','Atributos Personas Indemnización',NULL,'Verificar que la cobertura afectada de la póliza sea la correcta así como el año póliza correspondiente.',88,88),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.10','Atributos Personas Indemnización',NULL,'Validar que se realizó de forma adecuada y completa, el ajuste de daños, y cumple con el tipo de daño y piezas reclamadas.',89,89),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.11','Atributos Personas Indemnización',NULL,'Valide que existan las fotos de rigor y adicionales del siniestro establecidas en la normativa (físicas o electrónicas) y que las mismas sean claras y suficientes.',90,90),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.12','Atributos Personas Indemnización',NULL,'Validar que se haya realizado la notificación del siniestro a la Ofic. Ppal. a más tardar al día habil siguiente de recibido los soporte.',91,91),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.13','Atributos Personas Indemnización',NULL,'Verificar que la constitución de reserva y el monto que se registren en Sistema estén acorde a los tiempos y parámetros establecidos en la Normativa.',92,92),
    ('FIN_PERSONAL_RECLAMO','AC-B.2.2.14','Atributos Personas Indemnización',NULL,'Verificar que los siniestros sean pagados o rechazados dentro de los lapsos establecidos en la normativa.',93,93),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.1','Atributos Patrimonial Indemnización',NULL,'Verificar que los expedientes solicitados sean recibidos de manera satisfactoria.',96,96),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.2','Atributos Patrimonial Indemnización',NULL,'Verificar que el expediente de siniestro contenga la declaración formal elaborada por el Asegurado, debidamente llena en los campos requeridos y que se encuentre firmada por el Asegurado.',97,97),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.3','Atributos Patrimonial Indemnización',NULL,'Verificar que los reclamos sean notificados en los tiempos establecidos en las condiciones de la póliza.',98,98),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.4','Atributos Patrimonial Indemnización',NULL,'Validar que la documentación presente el sello de recibido por parte de la sucursal.',99,99),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.5','Atributos Patrimonial Indemnización',NULL,'Verifique que los expedientes de siniestros contengan toda la documentación requerida de acuerdo a la Normativa y al tipo de siniestro. (Físico, digital o electrónico).',100,100),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.6','Atributos Patrimonial Indemnización',NULL,'Verificar que la constitución de reserva y el monto que se registren en Sistema estén acorde a los tiempos y parámetros establecidos en la Normativa.',101,101),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.7','Atributos Patrimonial Indemnización',NULL,'Verificar el adecuado registro en Sistema de las causas.',102,102),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.8','Atributos Patrimonial Indemnización',NULL,'Verificar que la cobertura afectada de la póliza sea la correcta así como el año póliza correspondiente.',103,103),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.9','Atributos Patrimonial Indemnización',NULL,'Validar que se haya realizado la notificación del siniestro a la Ofic. Ppal. a más tardar al día habil siguiente de recibido los soporte.',104,104),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.10','Atributos Patrimonial Indemnización',NULL,'Gestiones siniestros pendientes > 45 días.',105,105),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.11','Atributos Patrimonial Indemnización',NULL,'Verificar el respectivo seguimiento por parte de la sucursal.',106,106),
    ('FIN_PATRIMONIAL_RECLAMO','AC-B.2.3.12','Atributos Patrimonial Indemnización',NULL,'Verificar que los siniestros sean pagados o rechazados dentro de los lapsos establecidos en la normativa.',107,107),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.1','Atributos Suscripción Patrimonial',NULL,'Verificar que los expedientes solicitados sean recibidos de manera satisfactoria.',110,110),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.2','Atributos Suscripción Patrimonial',NULL,'Verificar que el Contrato cuente con la Solicitud de Seguros',111,111),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.3','Atributos Suscripción Patrimonial',NULL,'Constatar la integridad, oportunidad y vigencia de la documentaciòn del Tomador, Asegurado y Beneficiario, con los soportes técnicos del riesgo (informes de inspección, avalúos y hojas de análisis de suscripción) que conforman el contrato Ramos Patrimoniales.',112,112),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.4','Atributos Suscripción Patrimonial',NULL,'Verificar que el cuadro de póliza y sus anexos cumplan con las condiciones de coberturas de riesgo (limite de responsabilidad, forma de valuación, deducible, etc.) Asi como los datos del bien (Nombre, dirección, etc).',113,113),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.5','Atributos Suscripción Patrimonial',NULL,'Verificar y Comprobar  la Tasa aplicada a la Prima Cobrada, acorde al rango de tasas segùn Polìticas internas.',114,114),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.6','Atributos Suscripción Patrimonial',NULL,'Validar que la fecha inicio de vigencia del Recibo o Factura de pòliza, concuerde con la fecha de recepción de Solicitud de Seguro o con la fecha de emisión de Notas de Cobertura Provisional (conforme al Art. 30 Normas Relación Contractual/Providencia SUDEASEG, Patrimoniales), para asegurar la oportuna detecciòn de los riesgos asociados.',115,115),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.7','Atributos Suscripción Patrimonial',NULL,'Verificar que el cobro de la prima se haya realizado en un maximo de 30 días continuos.',116,116),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.8','Atributos Suscripción Patrimonial',NULL,'Verificar cumplimiento condiciones obligatorias de asegurabilidad del bien o interés patrimonial objeto de cobertura. (Acorde a pautas de suscripción de empresa y Providencia SUDEASEG Patrimoniales). Comprende: a) Titularidad o soporte del interés asegurable; b) Informe de inspección de riesgo previo o justificación de exención; c) Avalúo técnico o comprobante de valorización que fundamente la suma asegurada; d) Disposición de medidas de seguridad y protección exigidas por clase de riesgo; y e) Solicitud de seguro firmada con la declaración exacta de ubicación y uso.',117,117),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.9','Atributos Suscripción Patrimonial',NULL,'Verificar si se cumple con los Factores que determinan el Riesgos. Aplicable para: Incendio / Todo Riesgo Industrial',118,118),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.10','Atributos Suscripción Patrimonial',NULL,'Validar que las pólizas suscritas correspondan a riesgos asegurables de acuerdo a las políticas y normas establecidas.',119,119),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.11','Atributos Suscripción Patrimonial',NULL,'Verificar que los resultados de inspecciones de riesgos, sean reflejadas en anexo en el Sistema Acsel/X, con detalle de observaciones y/o recomendaciones segùn el caso.',120,120),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.12','Atributos Suscripción Patrimonial',NULL,'Validar que los datos del asegurado y/ o tomador de la póliza (Nombre, apellido, C.I. telefono, correo, cuenta bancaria).registradosen en el sistema Acsel/X, se correpondan con la solicitud de seguros.',121,121),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AC-B.1.2.13','Atributos Suscripción Patrimonial',NULL,'Verificar que los Equipos electrònicos amparados, reflejen las especificaciones de la solicitud de seguros. En cuanto a marca, modelo, serial, valor de reposicion.',122,122),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.1','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Validar que la solicitud de seguros se encuentre debidamente completada en todos sus campos, firmada y con la huella dactilar del solicitante, incluyendo la Declaraciòn Jurada de Origen de Fondos.',124,124),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.2','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Verificar existencia de Contrato suscrito (Anexos, Condicionados). Validar la Identificación del Beneficiario Final.',125,125),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.3','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Verificar Documentaciòn de identidad del solicitante: C.I o Pasaporte /  RIF y su debida  validaciòn en Portales WEB Pùblicos (CNE , SENIAT y/o SSO), a fines de comprobar su autenticidad.',126,126),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.4','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Verificar que el expediente cuente con Referencias Bancarias, Ultima declaracion I.S.L.R.',127,127),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.5','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Verificar existencias de Registro Mercantil / Documento Constitutivo / Acta  Asamblea  Accionistas (Modificaciones). Casos de Renovcaciones, debe existir Constancia de Actualizaciòn de Datos (frecuencia anual).',128,128),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.6','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Verificar la debida diligencia cuando una Persona es Políticamente Expuesta.',129,129),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.7','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Validar el Soporte de Riesgo para las operaciones en Actividades y Profesiones No Financieras Designadas.',130,130),
    ('FIN_PATRIMONIAL_SUSCRIPCION','AR\LC PATRIM  1.8','Atributos Suscripción Patrimonial','AR-LC-FT-FPADM y otros ilícitos','Soporte de calificación de Riesgo efectuado por la UAR (Art 25, 26, 27).',131,131) 
ON CONFLICT (template_code, source_id) DO UPDATE SET
    section=EXCLUDED.section,
    subsection=EXCLUDED.subsection,
    criterion_text=EXCLUDED.criterion_text,
    sort_order=EXCLUDED.sort_order,
    excel_row=EXCLUDED.excel_row
WHERE engagement.financial_criteria.weight IS NULL;

GRANT SELECT, INSERT, UPDATE ON engagement.financial_templates, engagement.financial_criteria, engagement.signature_assets TO app_rw;

COMMIT;
