-- 031: continuidad del flujo de aprobación (suplencias temporales), baja definitiva de usuarios
-- con aprobación del Contralor y reglas de los motores editables con doble control.
--
-- Suplencias: el titular de una etapa (Jefe de Auditoría, Gerencia o Contralor) delega en otra
-- persona por un plazo máximo de 90 días. El flujo de estados del informe no cambia: el suplente
-- actúa en esa etapa y la transición queda registrada "en nombre de" el titular.

-- ---------------------------------------------------------------- baja definitiva de usuarios
-- Baja lógica: la cuenta se conserva porque la bitácora y las firmas apuntan a ella.
ALTER TABLE iam.users ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ;
ALTER TABLE iam.users ADD COLUMN IF NOT EXISTS removed_by UUID REFERENCES iam.users(id);
ALTER TABLE iam.users ADD COLUMN IF NOT EXISTS removal_reason TEXT;
ALTER TABLE iam.users ADD CONSTRAINT users_removed_inactive CHECK (removed_at IS NULL OR NOT is_active);

CREATE TABLE iam.user_removal_requests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_user_id UUID NOT NULL REFERENCES iam.users(id),
    reason         TEXT NOT NULL CHECK (length(btrim(reason)) >= 15),
    requested_by   UUID NOT NULL REFERENCES iam.users(id),
    status         VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    decided_by     UUID REFERENCES iam.users(id),
    decided_at     TIMESTAMPTZ,
    decision_note  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (requested_by <> target_user_id),
    CHECK (decided_by IS NULL OR (decided_by <> requested_by AND decided_by <> target_user_id))
);
CREATE UNIQUE INDEX user_removal_one_pending ON iam.user_removal_requests (target_user_id) WHERE status = 'PENDING';
GRANT SELECT, INSERT, UPDATE ON iam.user_removal_requests TO app_rw;

-- ---------------------------------------------------------------- catálogo del motor de Sistemas
-- Antes fijo en observation_rules.DOMAINS; el dominio "general" es el de respaldo (sort_order 999).
CREATE TABLE engagement.systems_rule_catalog (
    domain_key     VARCHAR(30) PRIMARY KEY CHECK (domain_key ~ '^[a-z][a-z0-9_]{1,29}$'),
    label          TEXT NOT NULL,
    keywords       TEXT[] NOT NULL DEFAULT '{}',
    criteria       TEXT NOT NULL,
    cause          TEXT NOT NULL,
    effect         TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    field_test     TEXT NOT NULL,
    critical       BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order     INT NOT NULL DEFAULT 100,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by     UUID,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (domain_key <> 'general' OR active)
);
GRANT SELECT, INSERT, UPDATE ON engagement.systems_rule_catalog TO app_rw;
INSERT INTO engagement.systems_rule_catalog
    (domain_key, label, keywords, criteria, cause, effect, recommendation, field_test, critical, sort_order) VALUES
    ('accesos', 'gestión de accesos e identidades', ARRAY['acceso', 'cuentas de usuario', 'alta de usuario', 'baja de usuario', 'usuarios privilegiados', 'usuarios genericos', 'contrasena', 'password', 'privilegi', 'autentic', 'credencial', 'perfiles de', 'roles y', 'segregacion de funciones', 'mfa', 'doble factor', 'sesion']::text[],
     'ISO/IEC 27001:2022 Anexo A 5.15 (control de acceso), 5.16 (gestión de identidades), 5.18 (derechos de acceso) y 8.5 (autenticación segura); COBIT 2019 DSS05.04 (gestionar la identidad y el acceso lógico); CIS Controls v8, controles 5 y 6.',
     'No existe un procedimiento formal y aprobado de altas, bajas y revisión periódica de accesos, ni una herramienta que centralice las identidades; la asignación de privilegios depende de solicitudes informales y no se revisa de forma recurrente.',
     'Cuentas activas de personal desvinculado, privilegios excesivos o contraseñas débiles permiten el acceso no autorizado a sistemas y datos de clientes y pólizas, con riesgo de fraude interno, fuga de información, despliegue de ransomware con credenciales comprometidas y sanciones del ente regulador por fallas en la protección de datos.',
     'Formalizar y aprobar la política y el procedimiento de gestión de accesos (alta, modificación, baja y revisión trimestral de privilegios), implementar autenticación multifactor en accesos remotos y administrativos, depurar las cuentas no justificadas y conservar evidencia de cada revisión.',
     'Seleccionar una muestra de usuarios activos y privilegiados, cotejarla con la nómina vigente y con las solicitudes aprobadas, y verificar la última revisión periódica de accesos y la configuración de contraseñas y MFA.', TRUE, 10),
    ('respaldos', 'respaldo y recuperación de la información', ARRAY['respaldo', 'backup', 'copia de seguridad', 'copias de seguridad', 'restaur', 'recuperacion de datos']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.13 (respaldo de la información); COBIT 2019 DSS04.07 (gestionar los respaldos); CIS Controls v8, control 11 (recuperación de datos).',
     'La ejecución de respaldos no está definida en un procedimiento con frecuencia, retención, custodia fuera de sitio y pruebas de restauración; no hay un responsable asignado ni monitoreo de los resultados de las tareas programadas.',
     'Ante un ataque de ransomware, una falla de hardware o un borrado accidental, la organización podría no recuperar información crítica (pólizas, siniestros, contabilidad), con interrupción prolongada de operaciones, pérdida de datos irrecuperable y exposición a multas por incumplimiento de las obligaciones de conservación de registros.',
     'Documentar y aprobar la política de respaldos (alcance, frecuencia, retención, copias inmutables o fuera de línea), asignar responsables, monitorear cada ejecución y realizar pruebas de restauración al menos trimestrales con acta firmada.',
     'Revisar la bitácora de respaldos del último período, verificar la existencia de copias fuera de sitio o inmutables y presenciar una restauración de prueba de un sistema crítico.', TRUE, 20),
    ('cambios', 'gestión de cambios y desarrollo', ARRAY['cambio', 'desarrollo', 'pase a produccion', 'despliegue', 'release', 'codigo fuente', 'ambiente de prueba', 'ambientes', 'personaliz', 'customiz']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.25 (ciclo de vida de desarrollo seguro), 8.31 (separación de ambientes) y 8.32 (gestión de cambios); COBIT 2019 BAI06 (gestionar los cambios de TI); CIS Controls v8, control 16.',
     'No existe un procedimiento formal de gestión de cambios con solicitud, evaluación de impacto, aprobación, pruebas y plan de reversión; los cambios se aplican directamente sin segregación entre desarrollo, pruebas y producción.',
     'Cambios no autorizados o no probados pueden interrumpir los sistemas centrales, introducir errores en el cálculo de primas y reservas, abrir puertas traseras o facilitar fraudes internos sin trazabilidad del responsable.',
     'Implementar un procedimiento de gestión de cambios con comité o aprobador designado, registro de cada solicitud, pruebas documentadas, segregación de ambientes y plan de reversión, y conservar la evidencia de cada pase a producción.',
     'Tomar una muestra de pases a producción del período y verificar solicitud, aprobación, pruebas, plan de reversión y que quien desarrolló no fue quien aprobó o desplegó el cambio.', FALSE, 30),
    ('registros', 'registro y monitoreo de eventos', ARRAY['log ', 'logs', 'bitacora', 'registro de eventos', 'monitoreo', 'monitorizacion', 'auditoria de eventos', 'siem', 'alerta', 'trazabilidad', 'pista de auditoria', 'pistas de auditoria', 'audit trail', 'registro de auditoria']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.15 (registro de eventos) y 8.16 (actividades de monitoreo); COBIT 2019 DSS05.07 (gestionar la supervisión de la infraestructura); CIS Controls v8, control 8.',
     'No se ha definido qué eventos deben registrarse, cuánto tiempo se conservan ni quién los revisa; no se dispone de una herramienta de centralización y correlación de registros.',
     'Un intruso o un usuario interno podría actuar sin ser detectado y borrar sus rastros; la ausencia de registros impide la investigación forense de incidentes, de fraudes y la atención de requerimientos legales o regulatorios.',
     'Definir y aprobar la política de registro y monitoreo (eventos mínimos, retención, protección contra alteración), centralizar los registros de sistemas críticos y establecer revisiones periódicas con alertas sobre eventos de riesgo.',
     'Solicitar los registros de un sistema crítico para una fecha determinada, verificar su integridad, retención y la evidencia de revisión o de alertas atendidas.', FALSE, 40),
    ('vulnerabilidades', 'gestión de parches y vulnerabilidades', ARRAY['parche', 'actualizacion', 'vulnerab', 'escaneo', 'pentest', 'prueba de penetracion', 'obsolet', 'fin de soporte']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.8 (gestión de vulnerabilidades técnicas); COBIT 2019 DSS05.01 (protección contra software malicioso) y BAI03; CIS Controls v8, control 7 (gestión continua de vulnerabilidades).',
     'No existe un proceso formal de inventario de vulnerabilidades, priorización y aplicación de parches con plazos definidos; las actualizaciones se aplican de forma reactiva y sin registro.',
     'Vulnerabilidades conocidas y sin corregir son el vector habitual de ransomware y de intrusiones remotas; su explotación puede paralizar la operación, cifrar o exfiltrar datos de asegurados y derivar en pérdidas económicas y reputacionales.',
     'Implementar un programa de gestión de vulnerabilidades con escaneos periódicos, criterios de criticidad, plazos máximos de corrección y reportes a la gerencia, y reemplazar o aislar los sistemas sin soporte del fabricante.',
     'Revisar el último escaneo de vulnerabilidades y el estado de parches de una muestra de servidores y estaciones, comparando contra los boletines del fabricante.', TRUE, 50),
    ('malware', 'protección contra código malicioso', ARRAY['antivirus', 'malware', 'edr', 'endpoint', 'virus', 'ransomware']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.7 (protección contra malware); COBIT 2019 DSS05.01; CIS Controls v8, control 10 (defensas contra malware).',
     'La protección contra malware no está gestionada de forma centralizada ni cubierta por un procedimiento que asegure su instalación, actualización y atención de alertas en todos los equipos.',
     'Equipos sin protección o con firmas desactualizadas facilitan la infección por ransomware y troyanos bancarios, con cifrado de información, robo de credenciales y propagación lateral en la red corporativa.',
     'Desplegar una solución antimalware/EDR administrada centralmente en todos los equipos y servidores, monitorear su cobertura y actualización, y documentar el procedimiento de atención de alertas.',
     'Verificar en la consola central la cobertura y la fecha de actualización de firmas en una muestra de equipos y la atención de las alertas recientes.', TRUE, 60),
    ('redes', 'seguridad de redes y telecomunicaciones', ARRAY['firewall', 'cortafuego', 'red ', 'redes', 'vpn', 'wifi', 'wi-fi', 'inalambric', 'segment', 'switch', 'router', 'telecom', 'perimetr', 'puerto']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.20 (seguridad de redes), 8.21 (seguridad de los servicios de red) y 8.22 (segregación de redes); COBIT 2019 DSS05.02; CIS Controls v8, controles 12 y 13.',
     'La configuración de la red no está documentada ni sometida a revisiones periódicas de reglas; no existe segmentación formal entre redes de usuarios, servidores y terceros.',
     'Una red plana o con reglas permisivas permite que un atacante que comprometa un equipo se desplace hasta los servidores críticos, exfiltre información o despliegue ransomware en toda la organización.',
     'Documentar la arquitectura de red, segmentar las zonas críticas, revisar y depurar semestralmente las reglas del firewall con aprobación formal, y asegurar los accesos remotos mediante VPN con autenticación multifactor.',
     'Obtener la configuración vigente del firewall, verificar las reglas de una muestra contra su justificación aprobada y comprobar la segmentación entre redes de usuarios y servidores.', FALSE, 70),
    ('cifrado', 'cifrado y protección de datos', ARRAY['cifrad', 'encript', 'certificado', 'ssl', 'tls', 'datos personales', 'confidencial', 'clasificacion de la informacion']::text[],
     'ISO/IEC 27001:2022 Anexo A 5.12 (clasificación de la información), 5.34 (privacidad y protección de datos personales) y 8.24 (uso de criptografía); COBIT 2019 DSS05.03; CIS Controls v8, control 3 (protección de datos).',
     'No se ha clasificado la información ni definido qué datos deben cifrarse en reposo y en tránsito; no existe gestión del ciclo de vida de llaves y certificados.',
     'La pérdida o interceptación de información no cifrada (bases de datos, respaldos, equipos portátiles) expone datos de asegurados y de la operación, con responsabilidad legal, sanciones regulatorias y daño reputacional.',
     'Aprobar la política de clasificación y cifrado de la información, cifrar los datos sensibles en reposo y en tránsito, y llevar un inventario de certificados y llaves con responsables y fechas de vencimiento.',
     'Verificar en una muestra de sistemas y respaldos que los datos sensibles se almacenan y transmiten cifrados y revisar la vigencia de los certificados publicados.', FALSE, 80),
    ('continuidad', 'continuidad del negocio y recuperación ante desastres', ARRAY['continuidad', 'contingencia', 'desastre', 'drp', 'bcp', 'alta disponibilidad', 'sitio alterno', 'recuperacion ante', 'failover', 'rto', 'rpo', 'downtime']::text[],
     'ISO/IEC 27001:2022 Anexo A 5.29 (seguridad durante una disrupción) y 5.30 (preparación de las TIC para la continuidad); COBIT 2019 DSS04 (gestionar la continuidad); CIS Controls v8, control 11.',
     'No existe un plan de continuidad y recuperación de TI aprobado, con tiempos objetivo de recuperación, responsables y pruebas periódicas.',
     'Ante una contingencia mayor (ransomware, falla del centro de datos, desastre natural) la organización no podría restablecer a tiempo la emisión de pólizas y el pago de siniestros, con pérdidas económicas e incumplimientos regulatorios.',
     'Elaborar y aprobar el plan de recuperación de TI con análisis de impacto, RTO/RPO por sistema y roles definidos, y ejecutar pruebas al menos anuales con informe de resultados y acciones de mejora.',
     'Revisar el plan vigente, su aprobación y el informe de la última prueba, verificando que los tiempos alcanzados cumplen los objetivos definidos.', TRUE, 90),
    ('incidentes', 'gestión de incidentes de seguridad', ARRAY['incidente', 'brecha', 'respuesta a', 'forense', 'csirt']::text[],
     'ISO/IEC 27001:2022 Anexo A 5.24 a 5.28 (gestión de incidentes de seguridad de la información); COBIT 2019 DSS02; CIS Controls v8, control 17.',
     'No se ha formalizado un procedimiento de reporte, clasificación, contención y lecciones aprendidas de incidentes, ni un equipo responsable con roles definidos.',
     'La respuesta improvisada ante un incidente amplía su impacto: mayor tiempo de indisponibilidad, pérdida de evidencia, propagación del ataque y notificaciones tardías a clientes y reguladores.',
     'Aprobar el procedimiento de gestión de incidentes con matriz de escalamiento, registro único de incidentes, plantillas de comunicación y ejercicios periódicos de simulación.',
     'Revisar el registro de incidentes del período y una muestra de casos cerrados, verificando clasificación, tiempos de atención, evidencias y lecciones aprendidas.', FALSE, 100),
    ('activos', 'inventario de activos y licenciamiento', ARRAY['inventario', 'activo', 'licencia', 'licenciamiento', 'hardware', 'software instalado', 'equipo de computo', 'equipos']::text[],
     'ISO/IEC 27001:2022 Anexo A 5.9 (inventario de información y otros activos) y 5.32 (derechos de propiedad intelectual); COBIT 2019 BAI09 (gestionar los activos); CIS Controls v8, controles 1 y 2.',
     'No existe un inventario actualizado y conciliado de hardware y software con responsables asignados, ni un control del licenciamiento instalado.',
     'Sin inventario no es posible proteger, parchar ni recuperar los activos; equipos no controlados se convierten en puntos de entrada para atacantes y el software sin licencia expone a sanciones legales.',
     'Implementar un inventario automatizado de hardware y software, conciliarlo periódicamente con los registros contables y de licencias, y asignar un custodio a cada activo.',
     'Seleccionar una muestra de equipos físicos y verificar su registro en el inventario, su custodio y el licenciamiento del software instalado.', FALSE, 110),
    ('terceros', 'gestión de proveedores y servicios de terceros', ARRAY['proveedor', 'tercero', 'outsourcing', 'contrato', 'nube', 'cloud', 'acuerdo de nivel', 'sla', 'escrow', 'custodia', 'fabricante']::text[],
     'ISO/IEC 27001:2022 Anexo A 5.19 a 5.23 (seguridad en las relaciones con proveedores y servicios en la nube); COBIT 2019 APO10 (gestionar los proveedores); CIS Controls v8, control 15.',
     'Los contratos con proveedores de TI no incluyen cláusulas de seguridad, confidencialidad y niveles de servicio, ni se evalúa periódicamente su cumplimiento.',
     'Un proveedor con accesos o datos de la organización y controles débiles puede originar fugas de información, interrupciones del servicio o ataques a la cadena de suministro sin posibilidad de exigir responsabilidades.',
     'Incorporar cláusulas de seguridad, confidencialidad, auditoría y niveles de servicio en los contratos, mantener un registro de proveedores críticos y evaluar su desempeño y riesgos al menos una vez al año.',
     'Revisar los contratos de una muestra de proveedores críticos y la evidencia de la última evaluación de su cumplimiento.', FALSE, 120),
    ('configuracion', 'configuración segura de servidores y bases de datos', ARRAY['servidor', 'base de datos', 'bases de datos', 'configuracion', 'hardening', 'sistema operativo', 'dba', 'motor']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.9 (gestión de la configuración) y 8.3 (restricción del acceso a la información); COBIT 2019 BAI10 (gestionar la configuración); CIS Controls v8, control 4 y CIS Benchmarks del fabricante.',
     'No existen líneas base de configuración segura aprobadas para servidores y bases de datos, ni revisiones periódicas que detecten desviaciones.',
     'Configuraciones por defecto, servicios innecesarios o cuentas genéricas activas facilitan la intrusión y la alteración directa de datos de pólizas, siniestros o contabilidad, con riesgo de fraude y pérdida de integridad.',
     'Definir y aplicar líneas base de configuración segura según los CIS Benchmarks, eliminar cuentas y servicios innecesarios y verificar semestralmente el cumplimiento con herramientas automatizadas.',
     'Comparar la configuración de una muestra de servidores y bases de datos contra la línea base aprobada y verificar las cuentas con privilegios administrativos.', FALSE, 130),
    ('concienciacion', 'concienciación y capacitación en seguridad', ARRAY['capacitacion', 'concienciacion', 'concientizacion', ' formacion', 'entrenamiento', 'phishing', 'simulacro']::text[],
     'ISO/IEC 27001:2022 Anexo A 6.3 (concienciación, educación y formación); COBIT 2019 APO07.03; CIS Controls v8, control 14.',
     'No existe un programa anual de concienciación en seguridad con contenidos, cobertura y medición de resultados.',
     'El personal no capacitado es el principal vector de phishing y robo de credenciales, punto de partida frecuente de ransomware y fraudes por suplantación.',
     'Implementar un programa anual de concienciación con módulos obligatorios, simulaciones de phishing y medición de resultados reportada a la gerencia.',
     'Verificar el programa vigente, la lista de asistencia o finalización del último ciclo y los resultados de simulaciones.', FALSE, 140),
    ('ciclo_vida', 'ciclo de vida y obsolescencia tecnológica', ARRAY['fin de vida', 'eol', 'eos', 'fin de soporte', 'soporte tecnico', 'roadmap', 'migracion', 'obsolet', 'actualizacion o migracion', 'presupuesto', 'version del erp', 'version actual']::text[],
     'ISO/IEC 27001:2022 Anexo A 8.8 (gestión de vulnerabilidades técnicas) y 5.37; COBIT 2019 APO02 (estrategia), APO04 (innovación) y BAI03 (soluciones); CIS Controls v8, control 2.2 (software con soporte del fabricante).',
     'La gerencia de TI no ha formalizado un plan de ciclo de vida de la plataforma con fechas de fin de soporte, presupuesto y responsables, por lo que la renovación tecnológica depende de decisiones reactivas.',
     'Operar sistemas sin soporte del fabricante impide recibir parches de seguridad: vulnerabilidades conocidas quedan abiertas para ransomware y fraudes, y una falla mayor podría no tener asistencia técnica, paralizando la operación.',
     'Documentar y aprobar el roadmap de actualización o migración con fechas de fin de soporte del fabricante, presupuesto asignado y responsables, y definir controles compensatorios mientras se ejecuta.',
     'Verificar con el fabricante las fechas de EOL/EOS de la versión en producción y revisar el roadmap aprobado y su presupuesto.', FALSE, 150),
    ('riesgos', 'gestión de riesgos tecnológicos y criticidad', ARRAY['riesgo', 'matriz', 'criticidad', 'bia', 'impacto al negocio', 'clasificacion formal']::text[],
     'ISO/IEC 27001:2022 cláusulas 6.1.2 (evaluación de riesgos) y 8.2; ISO/IEC 27005; COBIT 2019 APO12 (gestionar el riesgo) y EDM03.',
     'No existe una metodología formal de evaluación de riesgos tecnológicos ni un análisis de impacto al negocio que clasifique la criticidad de los sistemas.',
     'Sin conocer la criticidad de cada sistema, los recursos de protección y recuperación se asignan sin prioridad: un incidente sobre un sistema crítico podría tener un impacto financiero y regulatorio no previsto.',
     'Aprobar la metodología de gestión de riesgos tecnológicos, realizar el BIA, registrar la criticidad de cada sistema en la matriz de riesgos y actualizarla al menos una vez al año.',
     'Revisar la matriz de riesgos y el BIA vigentes, su aprobación y la inclusión del sistema auditado con su criticidad.', FALSE, 160),
    ('gobierno', 'gobierno y políticas de seguridad de la información', ARRAY['politica', 'procedimiento', 'manual', 'norma', 'gobierno', 'comite', 'responsable', 'aprobad', 'lineamiento', 'estrategia', 'plan ']::text[],
     'ISO/IEC 27001:2022 cláusulas 5.2 (política) y 7.5 (información documentada), Anexo A 5.1 (políticas de seguridad) y 5.37 (procedimientos operativos documentados); COBIT 2019 APO01 y EDM01.',
     'La unidad no ha formalizado el documento rector del control ni definido responsables de su elaboración, aprobación, divulgación y revisión periódica; la práctica descansa en el conocimiento de personas clave.',
     'Sin lineamientos aprobados los controles se aplican de forma inconsistente, no pueden exigirse ni auditarse y dependen de personas específicas, lo que aumenta la probabilidad de errores, fraudes y observaciones del ente regulador.',
     'Elaborar, aprobar por la instancia competente y divulgar el documento formal del control, asignar su responsable, establecer su revisión al menos anual y conservar la evidencia de su aplicación.',
     'Verificar la existencia del documento aprobado y vigente, su divulgación al personal y una muestra de evidencias de su aplicación.', FALSE, 170),
    ('general', 'tecnología de la información', '{}'::text[],
     'ISO/IEC 27001:2022 cláusula 6.1 (acciones para tratar riesgos) y controles aplicables del Anexo A; COBIT 2019 DSS05 (gestionar los servicios de seguridad); CIS Controls v8.',
     'El control no ha sido formalizado mediante un proceso documentado, con responsables, herramientas de soporte y supervisión de la gerencia de TI.',
     'La ausencia o debilidad del control aumenta la exposición de los sistemas y de la información de la aseguradora a accesos no autorizados, interrupciones del servicio, fraudes y sanciones regulatorias.',
     'Diseñar, documentar y aprobar el control, asignar su responsable, implementarlo con las herramientas necesarias y conservar evidencia periódica de su ejecución para el seguimiento de auditoría.',
     'Verificar en sitio la ejecución del control con evidencia del período auditado y entrevistar al responsable.', FALSE, 999)
ON CONFLICT (domain_key) DO NOTHING;

ALTER TABLE engagement.regulatory_catalog ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE engagement.regulatory_catalog ADD CONSTRAINT regulatory_catalog_general_active CHECK (topic <> 'general' OR active);

-- ---------------------------------------------------------------- cambios de reglas (doble control)
-- El Administrador del Sistema propone; el Contralor aprueba. Quien propone no aprueba.
CREATE TABLE engagement.rule_change_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engine        VARCHAR(10) NOT NULL CHECK (engine IN ('SUDEASEG','SISTEMAS','ANALITICO')),
    rule_key      VARCHAR(40) NOT NULL,
    payload       JSONB NOT NULL,
    previous      JSONB,
    reason        TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
    requested_by  UUID NOT NULL REFERENCES iam.users(id),
    status        VARCHAR(10) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    decided_by    UUID REFERENCES iam.users(id),
    decided_at    TIMESTAMPTZ,
    decision_note TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (decided_by IS NULL OR decided_by <> requested_by)
);
CREATE UNIQUE INDEX rule_change_one_pending ON engagement.rule_change_requests (engine, rule_key) WHERE status = 'PENDING';
GRANT SELECT, INSERT, UPDATE ON engagement.rule_change_requests TO app_rw;

-- ---------------------------------------------------------------- suplencias temporales
CREATE TABLE engagement.delegations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stage         VARCHAR(10) NOT NULL CHECK (stage IN ('JEFE','GERENCIA','CONTRALOR')),
    audit_domain  VARCHAR(12) CHECK (audit_domain IN ('FINANCIERA','SISTEMAS','GENERAL')),
    titular_id    UUID NOT NULL REFERENCES iam.users(id),
    delegate_id   UUID NOT NULL REFERENCES iam.users(id),
    starts_on     DATE NOT NULL,
    ends_on       DATE NOT NULL,
    reason        TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
    authorized_by UUID NOT NULL REFERENCES iam.users(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at    TIMESTAMPTZ,
    revoked_by    UUID REFERENCES iam.users(id),
    revoke_reason TEXT,
    CHECK (titular_id <> delegate_id),
    CHECK (authorized_by <> delegate_id),
    CHECK (ends_on >= starts_on AND ends_on - starts_on <= 90),
    CHECK ((stage = 'JEFE') = (audit_domain IS NOT NULL))
);
CREATE INDEX delegations_delegate ON engagement.delegations (delegate_id) WHERE revoked_at IS NULL;
GRANT SELECT, INSERT, UPDATE ON engagement.delegations TO app_rw;

-- Certificado propio del suplente para firmar (PKCS#12 cifrado con AES-256-GCM en la aplicación).
CREATE TABLE engagement.signing_certificates (
    user_id              UUID PRIMARY KEY REFERENCES iam.users(id),
    p12_encrypted        TEXT NOT NULL,
    passphrase_encrypted TEXT NOT NULL,
    subject              TEXT,
    serial               TEXT,
    not_after            TIMESTAMPTZ,
    uploaded_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT SELECT, INSERT, UPDATE ON engagement.signing_certificates TO app_rw;

ALTER TABLE engagement.report_transitions ADD COLUMN IF NOT EXISTS delegation_id UUID REFERENCES engagement.delegations(id);
ALTER TABLE engagement.report_transitions ADD COLUMN IF NOT EXISTS on_behalf_of UUID REFERENCES iam.users(id);
