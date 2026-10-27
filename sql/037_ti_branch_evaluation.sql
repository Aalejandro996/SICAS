-- 037: Evaluación TI de la sucursal (ciberseguridad y segregación de funciones) en las auditorías operativas,
-- y resultados consolidados para el módulo del Jefe de Auditoría de Sistemas.
--
-- Fuente: Evaluación_TI_Sucursal.xlsx, hoja TI_Sucursal (sha256 ecaa3b322dc22346b10aaf46d5130fcf96963652856f34784affa8f3a413acab).
--   Módulo I (15 preguntas, «SI» es lo correcto) y Módulo II (5 preguntas, «SI» es un conflicto de perfiles / SoD).
--   Nivel por «SI» del Módulo I: >= 14 Nivel 1 Óptimo (riesgo bajo), >= 11 Nivel 2 Satisfactorio (medio-bajo),
--   >= 8 Nivel 3 Requiere mejoras (medio-alto), < 8 Nivel 4 Crítico (alto). Cualquier «SI» del Módulo II:
--   alerta de conflicto de roles y dictamen «Riesgo elevado (conflicto de perfiles)».
--   Nota del colaborador (decisión de Contraloría): % de «SI» del Módulo I; con conflicto de perfiles queda limitada
--   al nivel crítico (7 de 15). Nota de la cédula: promedio de los colaboradores entrevistados.

ALTER TABLE engagement.worksheets DROP CONSTRAINT IF EXISTS worksheets_kind_check;
ALTER TABLE engagement.worksheets ADD CONSTRAINT worksheets_kind_check CHECK (kind IN ('SUSCRIPCION', 'RECLAMO', 'SISTEMAS', 'CXP', 'CXC', 'ADMIN', 'CARTELERA', 'ADS', 'LOPCYMAT', 'SERV_SUC', 'TI_SUC'));

ALTER TABLE engagement.financial_templates DROP CONSTRAINT IF EXISTS financial_templates_kind_line_check;
ALTER TABLE engagement.financial_templates ADD CONSTRAINT financial_templates_kind_line_check CHECK (
    (kind = 'TRANSVERSAL' AND line IS NULL)
    OR (kind IN ('SUSCRIPCION', 'RECLAMO') AND line IN ('AUTO', 'PATRIMONIAL', 'PERSONAL'))
    OR (kind IN ('CXP', 'CXC', 'ADMIN', 'CARTELERA', 'ADS', 'LOPCYMAT', 'SERV_SUC', 'TI_SUC') AND line = 'GENERAL'));

INSERT INTO engagement.financial_templates (code, domain, kind, line, title, source_file, source_sheet, source_sha256, version, active) VALUES
    ('AUD_TI_SUC', 'FINANCIERA', 'TI_SUC', 'GENERAL', 'Evaluación TI de la sucursal', 'Evaluación_TI_Sucursal.xlsx', 'TI_Sucursal', 'ecaa3b322dc22346b10aaf46d5130fcf96963652856f34784affa8f3a413acab', 1, TRUE)
ON CONFLICT (code) DO NOTHING;

INSERT INTO engagement.financial_criteria (template_code, source_id, section, subsection, criterion_text, sort_order, excel_row, metadata) VALUES
    ('AUD_TI_SUC', 'TI-01', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Contraseñas robustas', 'Para ingresar a su equipo de trabajo, ¿el sistema le pide una clave con el uso de Mayusculas, minusculas, números y al menos un carácter especial?', 1, 9, '{"module": "I", "number": "1", "good": "SI", "topic": "Contraseñas robustas", "iso": "ISO/IEC 27001:2022 A.5.17 (información de autenticación) y A.8.5 (autenticación segura)", "cobit": "COBIT 2019 DSS05.04 (identidad y acceso lógico)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-02', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Autenticación de dos factores', 'Para ingresar a sus sistemas de trabajo, ¿el sistema le pide confirmar un código además de su clave?', 2, 10, '{"module": "I", "number": "2", "good": "SI", "topic": "Autenticación de dos factores", "iso": "ISO/IEC 27001:2022 A.8.5 (autenticación segura)", "cobit": "COBIT 2019 DSS05.04 (identidad y acceso lógico)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-03', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Instalación de software restringida', 'Si necesita instalar un programa nuevo en su computadora, ¿el sistema se lo impide y le solicita una clave de administrador?', 3, 11, '{"module": "I", "number": "3", "good": "SI", "topic": "Instalación de software restringida", "iso": "ISO/IEC 27001:2022 A.8.19 (instalación de software) y A.8.2 (derechos de acceso privilegiado)", "cobit": "COBIT 2019 DSS05.03 (seguridad de los puntos finales)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-04', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Conocimiento de políticas y procesos de TI', 'Conoce Ud donde se encuentran registradas las Politicas y Procesos de TI, CiberSeguridad?', 4, 12, '{"module": "I", "number": "4", "good": "SI", "topic": "Conocimiento de políticas y procesos de TI", "iso": "ISO/IEC 27001:2022 A.5.1 (políticas de seguridad) y A.6.3 (concienciación y formación)", "cobit": "COBIT 2019 APO01 (marco de gestión de TI) y APO13.01"}'::jsonb),
    ('AUD_TI_SUC', 'TI-05', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Política de ciberseguridad conocida', '¿A tenido acceso a la poitica de CiberSeguridad y conoce su alcance?', 5, 13, '{"module": "I", "number": "5", "good": "SI", "topic": "Política de ciberseguridad conocida", "iso": "ISO/IEC 27001:2022 A.5.1 (políticas de seguridad) y A.6.3 (concienciación y formación)", "cobit": "COBIT 2019 APO13.01 y APO07.03 (habilidades y competencias)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-06', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Canal de reporte de incidentes', '¿usted tiene concimiento del medio por el cual debe efectuar los reportes al equipo de TI?', 6, 14, '{"module": "I", "number": "6", "good": "SI", "topic": "Canal de reporte de incidentes", "iso": "ISO/IEC 27001:2022 A.6.8 (reporte de eventos de seguridad) y A.5.24 (planificación de la gestión de incidentes)", "cobit": "COBIT 2019 DSS02 (solicitudes e incidentes)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-07', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Alertas sobre adjuntos de correo', '¿Ha observado si su equipo notifica o presenta alertas descargar archivos que llegan adjuntos al correo?', 7, 15, '{"module": "I", "number": "7", "good": "SI", "topic": "Alertas sobre adjuntos de correo", "iso": "ISO/IEC 27001:2022 A.8.7 (protección contra malware)", "cobit": "COBIT 2019 DSS05.01 (protección contra software malicioso)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-08', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Actualizaciones del sistema', 'Cuando su computadora le muestra un mensaje para reiniciar e instalar actualizaciones del sistema, ¿Se reinicia ese mismo día de manera automatica?', 8, 16, '{"module": "I", "number": "8", "good": "SI", "topic": "Actualizaciones del sistema", "iso": "ISO/IEC 27001:2022 A.8.8 (gestión de vulnerabilidades técnicas)", "cobit": "COBIT 2019 DSS05.01 y DSS05.03"}'::jsonb),
    ('AUD_TI_SUC', 'TI-09', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Red para invitados', 'Si un visitante o familiar le pide internet en la oficina, ¿usted le proporciona la red destinada a invitados?', 9, 17, '{"module": "I", "number": "9", "good": "SI", "topic": "Red para invitados", "iso": "ISO/IEC 27001:2022 A.8.20 (seguridad de redes) y A.8.22 (segregación de redes)", "cobit": "COBIT 2019 DSS05.02 (seguridad de red y conectividad)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-10', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Aislamiento de la red principal', 'Si falla la conexión de Internet Invitados, ¿la conexión a la red principal le impide el Acceso?', 10, 18, '{"module": "I", "number": "10", "good": "SI", "topic": "Aislamiento de la red principal", "iso": "ISO/IEC 27001:2022 A.8.22 (segregación de redes)", "cobit": "COBIT 2019 DSS05.02 (seguridad de red y conectividad)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-11', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Revisión de medios extraíbles', 'Cuando le entregan una memoria pendrive para ver información, ¿usted solicita que la revisen o la pasa por una revisión antes de copiar los archivos?', 11, 19, '{"module": "I", "number": "11", "good": "SI", "topic": "Revisión de medios extraíbles", "iso": "ISO/IEC 27001:2022 A.7.10 (medios de almacenamiento) y A.8.7 (protección contra malware)", "cobit": "COBIT 2019 DSS05.03 (seguridad de los puntos finales)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-12', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Bloqueo de pantalla', 'Al levantarse de su escritorio para ir al baño o a una reunión, ¿usted acostumbra a bloquear la pantalla de su computadora para que nadie la use o se bloquea automaticamente?', 12, 20, '{"module": "I", "number": "12", "good": "SI", "topic": "Bloqueo de pantalla", "iso": "ISO/IEC 27001:2022 A.7.7 (escritorio y pantalla limpios) y A.8.1 (dispositivos de usuario final)", "cobit": "COBIT 2019 DSS05.03 (seguridad de los puntos finales)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-13', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Información en repositorios de la empresa', 'Sus archivos y documentos de trabajo importantes, ¿se encuentran guardados en las carpetas de la empresa?', 13, 21, '{"module": "I", "number": "13", "good": "SI", "topic": "Información en repositorios de la empresa", "iso": "ISO/IEC 27001:2022 A.8.13 (respaldo de la información) y A.5.10 (uso aceptable de la información)", "cobit": "COBIT 2019 DSS04.07 (respaldos)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-14', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Control de copias a redes alternas', 'Si intenta realizar una copia o respaldo de información de trabajo a una red alterna ¿el sistema le emite alguna alerta o restricción?', 14, 22, '{"module": "I", "number": "14", "good": "SI", "topic": "Control de copias a redes alternas", "iso": "ISO/IEC 27001:2022 A.8.12 (prevención de fuga de datos)", "cobit": "COBIT 2019 DSS05.03 y APO13"}'::jsonb),
    ('AUD_TI_SUC', 'TI-15', 'Módulo I: Prácticas de Ciberseguridad y Protección de Información', 'Control de dispositivos USB', 'SI conecta un Pendrive o un dispositivo alterno a la computadora por medio del USB ¿observa algun mensaje de alerta?', 15, 23, '{"module": "I", "number": "15", "good": "SI", "topic": "Control de dispositivos USB", "iso": "ISO/IEC 27001:2022 A.7.10 (medios de almacenamiento) y A.8.12 (prevención de fuga de datos)", "cobit": "COBIT 2019 DSS05.03 (seguridad de los puntos finales)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-16', 'Módulo II: Identificación de Perfiles y Segregación de Funciones', 'Usuarios múltiples por persona', 'Para cumplir con sus tareas diarias, ¿usted debe ingresar a los sistemas utilizando dos o más usuarios a su nombre?', 16, 27, '{"module": "II", "number": "16", "good": "NO", "topic": "Usuarios múltiples por persona", "iso": "ISO/IEC 27001:2022 A.5.16 (gestión de identidades) y A.5.18 (derechos de acceso)", "cobit": "COBIT 2019 DSS05.04 (identidad y acceso lógico)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-17', 'Módulo II: Identificación de Perfiles y Segregación de Funciones', 'Uso de usuarios ajenos', 'Para ejecutar sus tareas ¿accede al sistema con un usuario diferente al asignado?', 17, 28, '{"module": "II", "number": "17", "good": "NO", "topic": "Uso de usuarios ajenos", "iso": "ISO/IEC 27001:2022 A.5.16 (gestión de identidades) y A.5.17 (información de autenticación)", "cobit": "COBIT 2019 DSS05.04 (identidad y acceso lógico)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-18', 'Módulo II: Identificación de Perfiles y Segregación de Funciones', 'Funciones de otras áreas', '¿Usted realiza tareas o aprobaciones dentro del sistema que corresponden a otro departamento o a un puesto de trabajo distinto al suyo?', 18, 29, '{"module": "II", "number": "18", "good": "NO", "topic": "Funciones de otras áreas", "iso": "ISO/IEC 27001:2022 A.5.3 (segregación de funciones) y A.5.15 (control de acceso)", "cobit": "COBIT 2019 DSS06.03 (roles, privilegios y niveles de autoridad)"}'::jsonb),
    ('AUD_TI_SUC', 'TI-19', 'Módulo II: Identificación de Perfiles y Segregación de Funciones', 'Permisos de cargos anteriores', '¿Conserva acceso y permisos en los sistemas para realizar funciones que pertenecían a un cargo anterior que ocupaba en la empresa?', 19, 30, '{"module": "II", "number": "19", "good": "NO", "topic": "Permisos de cargos anteriores", "iso": "ISO/IEC 27001:2022 A.5.18 (derechos de acceso) y A.6.5 (responsabilidades tras cambio de empleo)", "cobit": "COBIT 2019 DSS05.04 y DSS06.03"}'::jsonb),
    ('AUD_TI_SUC', 'TI-20', 'Módulo II: Identificación de Perfiles y Segregación de Funciones', 'Registrar y aprobar el mismo trámite', 'En el proceso de su trabajo, ¿usted tiene la capacidad de crear/registrar un trámite y también aprobarlo o autorizarlo usted mismo en el sistema?', 20, 31, '{"module": "II", "number": "20", "good": "NO", "topic": "Registrar y aprobar el mismo trámite", "iso": "ISO/IEC 27001:2022 A.5.3 (segregación de funciones)", "cobit": "COBIT 2019 DSS06.03 (roles, privilegios y niveles de autoridad)"}'::jsonb)
ON CONFLICT (template_code, source_id) DO NOTHING;

-- Referencia SUDEASEG del informe: editable con doble control (Reglas de los motores › Normativa SUDEASEG).
INSERT INTO engagement.regulatory_catalog (topic, label, keywords, criteria, cause, effect, recommendation, sort_order, active) VALUES
    ('tecnologia_sucursal', 'tecnología y seguridad de la información en sucursales', ARRAY['evaluacion ti de la sucursal'],
     'Normativa de la SUDEASEG aplicable a la seguridad de la información y a la tecnología de las empresas de seguros (precise aquí la providencia vigente y sus artículos).',
     'Prácticas de seguridad no adoptadas por el personal o controles técnicos no configurados en los equipos de la sucursal.',
     'Exposición de la información de clientes y de la operación a accesos no autorizados, fuga de datos o código malicioso.',
     'Reforzar la configuración de los equipos y la concienciación del personal, y revisar los perfiles de acceso de la sucursal.',
     900, TRUE)
ON CONFLICT (topic) DO NOTHING;

-- Resultado consolidado de cada auditoría operativa cerrada (lo usa el módulo «Evaluación TI de sucursales»).
CREATE TABLE IF NOT EXISTS engagement.ti_branch_results (
    audit_id        UUID PRIMARY KEY REFERENCES engagement.audits(id),
    unit_id         INT NOT NULL,
    unit_code       TEXT,
    unit_name       TEXT NOT NULL,
    audit_code      TEXT NOT NULL,
    period_from     DATE,
    period_to       DATE,
    closed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    collaborators   INT NOT NULL CHECK (collaborators >= 0),
    score           NUMERIC(5,2),
    module1_pct     NUMERIC(5,2),
    level           SMALLINT CHECK (level BETWEEN 1 AND 4),
    risk            TEXT,
    sod_conflicts   INT NOT NULL DEFAULT 0,
    dictamen        TEXT,
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ti_branch_results_unit ON engagement.ti_branch_results(unit_id, closed_at DESC);
GRANT SELECT, INSERT, UPDATE ON engagement.ti_branch_results TO app_rw;
