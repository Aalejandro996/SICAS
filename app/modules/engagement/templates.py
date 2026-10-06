"""
Criterios base de las cédulas. SON UNA PROPUESTA GENÉRICA: deben ajustarse a las cédulas oficiales de la empresa
(el Contralor las edita desde la aplicación; cada cédula guarda una copia de los criterios con que se creó).
Cada criterio: code, text, weight (1 = normal, 2 = importante, 3 = crítico).
"""
from __future__ import annotations

KINDS = {"SUSCRIPCION": "Suscripción", "RECLAMO": "Reclamo / indemnización", "SISTEMAS": "Auditoría de Sistemas"}
LINES = {"AUTO": "Auto", "PATRIMONIAL": "Patrimonial", "PERSONAL": "Personal", "ERP_TI": "ERP / TI"}
TEMPLATE_KEYS = (("SUSCRIPCION", "AUTO"), ("SUSCRIPCION", "PATRIMONIAL"), ("SUSCRIPCION", "PERSONAL"), ("RECLAMO", "AUTO"), ("RECLAMO", "PATRIMONIAL"), ("RECLAMO", "PERSONAL"), ("SISTEMAS", "ERP_TI"))
RESULTS = ("CUMPLE", "PARCIAL", "NO_CUMPLE", "NO_APLICA", "EXCEPCION")
RESULT_LABEL = {"CUMPLE": "Cumple", "PARCIAL": "Cumple parcialmente", "NO_CUMPLE": "No cumple",
                "NO_APLICA": "No aplica", "EXCEPCION": "Excepción (información no recibida)"}

# Ramos del sistema de origen -> línea de la cédula (editable)
BRANCH_TO_LINE = {
    "AUTO": "AUTO", "AUTOMOVIL": "AUTO", "VEHICULOS": "AUTO",
    "HOGAR": "PATRIMONIAL", "INCENDIO": "PATRIMONIAL", "PATRIMONIAL": "PATRIMONIAL", "RIESGOS": "PATRIMONIAL", "TRANSPORTE": "PATRIMONIAL",
    "VIDA": "PERSONAL", "SALUD": "PERSONAL", "HCM": "PERSONAL", "ACCIDENTES": "PERSONAL", "FUNERARIO": "PERSONAL", "PERSONAL": "PERSONAL",
}


def branches_for_line(line: str) -> list[str]:
    return sorted(b for b, l in BRANCH_TO_LINE.items() if l == line)


def _c(prefix, rows):
    return [{"code": f"{prefix}{i:02d}", "text": t, "weight": w} for i, (t, w) in enumerate(rows, 1)]


KYC = ("Formulario de conocimiento del cliente (prevención de LC/FT) completo y vigente", 3)

DEFAULTS: dict[tuple[str, str], list[dict]] = {
    ("SUSCRIPCION", "AUTO"): _c("S", [
        ("Solicitud de seguro completa y firmada por el solicitante", 2),
        ("Documento de identidad / RIF del asegurado y copia en el expediente", 1),
        ("Documentos de propiedad del vehículo (certificado de registro / título)", 2),
        ("Inspección o fotografías del vehículo cuando aplica", 2),
        ("Suma asegurada coherente con el valor del vehículo (tabla o avalúo)", 3),
        ("Prima calculada con la tarifa vigente y los recargos/descuentos autorizados", 3),
        ("Pago o fraccionamiento de la prima conforme a lo autorizado", 2),
        ("Póliza emitida dentro de la vigencia solicitada y con las coberturas pedidas", 2),
        ("Intermediario autorizado y con comisión correcta", 1), KYC]),
    ("SUSCRIPCION", "PATRIMONIAL"): _c("S", [
        ("Solicitud de seguro completa y firmada por el solicitante", 2),
        ("Documento de identidad / RIF del asegurado y copia en el expediente", 1),
        ("Documento de propiedad o interés asegurable del bien", 2),
        ("Inspección de riesgo realizada y archivada (cuando aplica por monto o actividad)", 3),
        ("Suma asegurada conforme al valor de reposición (sin infraseguro)", 3),
        ("Deducibles y condiciones especiales aprobados según el nivel de autoridad", 2),
        ("Prima calculada con la tarifa vigente", 3),
        ("Pago o fraccionamiento de la prima conforme a lo autorizado", 2),
        ("Reaseguro o coaseguro registrado cuando la suma asegurada lo requiere", 2), KYC]),
    ("SUSCRIPCION", "PERSONAL"): _c("S", [
        ("Solicitud con declaración de asegurabilidad completa y firmada", 3),
        ("Documento de identidad del asegurado y copia en el expediente", 1),
        ("Requisitos médicos exigidos según edad y suma asegurada", 3),
        ("Edad del asegurado dentro de los límites de aceptación", 2),
        ("Beneficiarios designados y con datos completos", 2),
        ("Prima calculada con la tarifa y la tabla vigentes", 3),
        ("Pago o fraccionamiento de la prima conforme a lo autorizado", 2),
        ("Póliza emitida con las coberturas y exclusiones aprobadas", 2), KYC]),
    ("RECLAMO", "AUTO"): _c("R", [
        ("Aviso de siniestro dentro del plazo contractual", 2),
        ("Póliza vigente y prima al día en la fecha de ocurrencia", 3),
        ("La cobertura reclamada está contratada y no aplica exclusión", 3),
        ("Documentos del reclamo completos (denuncia / informe de tránsito, licencia, cédula)", 2),
        ("Inspección o peritaje realizado y archivado", 2),
        ("Presupuesto o facturas razonables y soportadas", 2),
        ("Reserva constituida y ajustada oportunamente", 2),
        ("Aprobación del pago según el nivel de autoridad", 3),
        ("Pago correcto en monto, deducible y beneficiario; plazo de liquidación cumplido", 3),
        ("Salvamento o recobro gestionado cuando aplica", 1)]),
    ("RECLAMO", "PATRIMONIAL"): _c("R", [
        ("Aviso de siniestro dentro del plazo contractual", 2),
        ("Póliza vigente y prima al día en la fecha de ocurrencia", 3),
        ("La cobertura reclamada está contratada y no aplica exclusión", 3),
        ("Inspección y ajuste de la pérdida por perito o ajustador", 3),
        ("Documentos de propiedad y de cuantificación de la pérdida", 2),
        ("Aplicación correcta de infraseguro y deducible", 3),
        ("Reserva constituida y ajustada oportunamente", 2),
        ("Aprobación del pago según el nivel de autoridad", 3),
        ("Pago correcto en monto y beneficiario; plazo de liquidación cumplido", 3),
        ("Recobro o subrogación gestionados cuando aplica", 1)]),
    ("RECLAMO", "PERSONAL"): _c("R", [
        ("Aviso de siniestro dentro del plazo contractual", 2),
        ("Póliza vigente y prima al día; periodos de carencia verificados", 3),
        ("La cobertura reclamada está contratada y no aplica exclusión ni preexistencia", 3),
        ("Informe médico / certificado o acta que soporta el evento", 3),
        ("Documentos del reclamante y del beneficiario completos", 2),
        ("Revisión médica o de la auditoría de reclamos documentada", 2),
        ("Reserva constituida y ajustada oportunamente", 2),
        ("Aprobación del pago según el nivel de autoridad", 3),
        ("Pago al beneficiario correcto, en el monto correcto y dentro del plazo", 3)]),
}


def default_criteria(kind: str, line: str) -> list[dict]:
    if kind == "SISTEMAS" and line == "ERP_TI":
        return system_erp_criteria()
    return [dict(c) for c in DEFAULTS[(kind, line)]]



# Cuestionario oficial de Auditoría de Sistemas / ERPs TI.
# Fuente: Cuestionario_ERPs_TI.xlsx (hoja "ERPs TI").
# El archivo declara 96 controles en su resumen, pero contiene 81 controles
# numerados (1-81). No se inventan los 15 controles faltantes.
SYSTEM_ERP_CONTROLS = [
    (1, '¿Cuáles son los módulos operativos habilitados actualmente en la versión en producción del ERP?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (2, '¿Qué procesos de negocio core (emisión, siniestros, reaseguro, contabilidad) son soportados directamente por el ERP sin herramientas periféricas?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (3, '¿Existen módulos adquiridos bajo la licencia del ERP que se encuentren totalmente inactivos?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (4, '¿Se ha identificado alguna funcionalidad habilitada en el ERP que presente un bajo nivel de utilización por los usuarios operativos?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (5, '¿El ERP cuenta con una clasificación formal de criticidad basada en los resultados del Análisis de Impacto al Negocio (BIA)?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (6, '¿Está registrado formalmente el nivel de criticidad del ERP dentro de la matriz de riesgos tecnológicos de la organización?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (7, '¿Cuál es la fecha oficial de Fin de Vida Útil (EOL) declarada por el fabricante para la versión del ERP desplegada?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (8, '¿Cuál es la fecha límite de Fin de Soporte Técnico (EOS) garantizada por el fabricante para la versión actual?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (9, '¿Cuenta la organización con un roadmap documentado para la actualización o migración del ERP antes del fin de su soporte?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (10, '¿Se cuenta con un presupuesto formalmente aprobado para ejecutar el plan de actualización o migración del ERP?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (11, '¿El plan de migración contempla la actualización o sustitución de los motores de base de datos subyacentes al ERP?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (12, '¿Existe un inventario actualizado de las personalizaciones (customizations/ABAP/scripts) desarrolladas sobre la versión estándar del ERP?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (13, '¿Se evalúa periódicamente el impacto técnico que tienen las personalizaciones en la capacidad de actualizar la versión del ERP?', '1. Funcionalidades, Alcance y Ciclo de Vida'),
    (14, '¿Cuál es el modelo de arquitectura y despliegue del ERP (desarrollo In-House, COTS On-Premise o SaaS/Cloud)?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (15, 'En desarrollos In-House, ¿se mantiene un repositorio centralizado y protegido para el almacenamiento del código fuente del ERP?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (16, 'En desarrollos In-House, ¿se dispone de documentación actualizada de la arquitectura de software y diccionarios de datos del ERP?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (17, 'En ERPs de terceros (COTS), ¿existe un acuerdo formal de custodia de código fuente (Escrow Agreement) suscrito y vigente?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (18, '¿Se valida periódicamente que el código depositado en la entidad de custodia (Escrow) corresponda a la versión en producción del ERP?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (19, '¿El esquema de licenciamiento contratado cubre el número actual de usuarios concurrentes que acceden a la plataforma?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (20, '¿La licencia contratada del ERP respalda el volumen transaccional operativo real que procesa la organización?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (21, '¿El contrato de licenciamiento autoriza formalmente la operación bajo el esquema multi-empresa configurado en el sistema?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (22, '¿Existe un inventario centralizado y actualizado de las APIs, Webhooks y servicios de integración vinculados al ERP?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (23, '¿Se aplican mecanismos de autenticación segura (ej. tokens API, OAuth) para el acceso a los servicios de integración del ERP?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (24, '¿Todas las comunicaciones entre el ERP y los sistemas periféricos se transmiten mediante canales cifrados (TLS 1.2+)?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (25, '¿Se aplican mecanismos de control de límites de tasa (rate limiting) para evitar la saturación o ataques de denegación de servicio sobre las APIs del ERP?', '2. Arquitectura de Software: In-House vs. Tercerizado'),
    (26, '¿El ERP tiene parametrizadas Matrices de Aprobación en el sistema para la autorización de transacciones financieras?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (27, '¿El sistema ejecuta reglas automatizadas de Segregación de Funciones (SoD) para impedir que un usuario cree y apruebe el mismo registro financiero?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (28, '¿La arquitectura de accesos del ERP está estructurada mediante el esquema de control de acceso basado en roles (RBAC)?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (29, '¿Se restringe el acceso de los usuarios exclusivamente a las funciones operativas indispensables para su perfil de puesto (Principio de Menor Privilegio)?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (30, '¿El ERP requiere de un flujo de aprobación jerárquica obligatoria previo al procesamiento de transacciones extraordinarias o ajustes masivos?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (31, '¿El sistema bloquea automáticamente la ejecución de transacciones fuera de perfil hasta recibir la autorización digital en sistema?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (32, '¿Existe un procedimiento formal para la baja o deshabilitación inmediata de cuentas en el ERP ante la desvinculación de personal?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (33, '¿Se efectúan conciliaciones periódicas entre la nómina activa de Talento Humano y las cuentas habilitadas en el ERP?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (34, '¿Se ajustan de forma inmediata los permisos y roles en el ERP cuando un colaborador cambia de puesto o área organizacional?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (35, "¿El uso de perfiles con privilegios elevados o 'Superusuario' (ej. SAP_ALL) está restringido al personal estrictamente autorizado?", '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (36, '¿Se requiere autenticación de doble factor (MFA) para el inicio de sesión de cuentas administradoras o superusuarios en el ERP?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (37, '¿Todas las acciones ejecutadas por perfiles de superusuario son registradas y consolidadas en logs de auditoría inalterables?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (38, '¿Existen revisiones periódicas (mínimo semestrales) de la matriz de roles y privilegios asignados a los usuarios en el ERP?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (39, '¿Se prohíbe explícitamente el uso de cuentas genéricas o compartidas para operar o administrar la plataforma ERP?', '3. Gestión de Accesos, Roles y Matrices de Aprobación (Seguridad)'),
    (40, '¿Existen Acuerdos de Nivel de Servicio (SLA) contractuales y vigentes formalizados con el proveedor del ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (41, '¿Se definen tiempos máximos de respuesta y resolución (MTTR) según la severidad de los incidentes en el SLA del ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (42, '¿El contrato con el proveedor contempla penalizaciones financieras por el incumplimiento de las métricas de SLA pactadas?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (43, '¿Se realizan comités técnicos periódicos con el proveedor para evaluar la gestión operativa y el soporte del ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (44, '¿Se evalúan métricas de disponibilidad (Uptime) e indicadores de resolución de fallas en las reuniones con el proveedor?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (45, '¿Se monitorea periódicamente el consumo de capacidad (procesamiento, almacenamiento) para prever requerimientos de infraestructura del ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (46, '¿Están definidos formalmente el Tiempo Objetivo de Recuperación (RTO) y el Punto Objetivo de Recuperación (RPO) para el ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (47, '¿El RTO y RPO definidos para el ERP se encuentran alineados con las exigencias de continuidad aprobadas por la alta gerencia?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (48, '¿El contrato de soporte del ERP garantiza la entrega y aplicación oportuna de parches de seguridad (Patch Management)?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (49, '¿Las actualizaciones de versión del ERP están cubiertas por la tarifa de mantenimiento sin generar costos adicionales?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (50, '¿Disponen las áreas operativas core de procedimientos manuales de contingencia (Downtime Procedures) documentados ante caídas del ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (51, '¿Se han realizado simulacros o capacitaciones sobre el uso de procedimientos manuales ante la indisponibilidad del ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (52, '¿Se ejecutan pruebas periódicas de restauración de respaldos de la base de datos del ERP para verificar la integridad de la información?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (53, '¿Se efectúan pruebas de conmutación por error (Failover) hacia la infraestructura de recuperación ante desastres (DRP) al menos una vez al año?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (54, '¿Se documentan y aprueban formalmente los resultados obtenidos en las pruebas de restauración y conmutación del ERP?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (55, '¿Existe un procedimiento definido para la puesta al día y sincronización transaccional tras la recuperación del ERP post-contingencia?', '4. Nivel de Servicio (SLA), Mantenimiento y Continuidad Operativa'),
    (56, 'En ERPs gestionados por terceros (SaaS/Cloud), ¿el proveedor entrega anualmente reportes de aseguramiento de controles (SOC 1 / SOC 2)?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (57, '¿Los informes SOC proporcionados se encuentran emitidos bajo estándares internacionales reconocidos (ISAE 3402 / SSAE 18)?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (58, '¿Dispone el proveedor de un informe SOC 1 Tipo II emitido por una firma de auditoría independiente?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (59, '¿El reporte SOC 1 Tipo II evalúa un período operativo no inferior a 6 meses para validar los controles sobre la información financiera?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (60, '¿Dispone la organización de un informe SOC 2 Tipo II vigente para la plataforma y servicios del ERP?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (61, '¿El reporte SOC 2 Tipo II evalúa explícitamente los principios de Seguridad, Disponibilidad y Confidencialidad de la información?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (62, "¿El área de Auditoría de Sistemas revisa exhaustivamente las desviaciones registradas en la sección de 'Excepciones' de los informes SOC?", '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (63, '¿Se elabora una evaluación de riesgo residual interno con base en los hallazgos y excepciones reportadas en el informe SOC?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (64, '¿Se han identificado los Controles Complementarios de la Entidad Usuaria (CUECs) requeridos por el proveedor en su informe SOC?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (65, '¿Se evalúa y prueba internamente la efectividad operativa de todos los CUECs bajo responsabilidad de la organización?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (66, 'En ausencia de reportes SOC Tipo II, ¿el contrato reserva el derecho explícito de la organización a auditar (Right to Audit) las instalaciones del proveedor?', '5. Informes SOC (Control de Organizaciones de Servicio) y Auditoría Externa'),
    (67, '¿El ERP genera de forma nativa e inalterable pistas de auditoría (Audit Trails) para las transacciones y cambios del sistema?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (68, '¿Las pistas de auditoría registradas capturan metadatos completos como fecha, hora, usuario identificable y dirección IP/estación?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (69, '¿El registro de auditoría del ERP conserva el detalle exacto del valor anterior y el valor posterior ante modificaciones de datos?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (70, '¿El ERP genera de forma directa y automatizada los reportes de cumplimiento exigidos por reguladores (ej. SUDEASEG / entes fiscales)?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (71, '¿Se evita la manipulación manual de datos en hojas de cálculo externas para la consolidación de información regulatoria?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (72, '¿Se encuentran cifrados en reposo (Encryption at Rest) los archivos y datos almacenados en la base de datos principal del ERP?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (73, '¿Se aplican mecanismos de cifrado específicos sobre campos que contienen información confidencial o sensible de clientes?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (74, '¿Se realizan análisis periódicos de vulnerabilidades dirigidos a la aplicación, servicios y componentes del ERP?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (75, '¿Se ejecutan pruebas de penetración (Pentesting) específicas sobre la capa web e interfaces del ERP al menos una vez al año?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (76, '¿Existe un plan de remediación documentado y monitoreado para corregir las vulnerabilidades halladas en las evaluaciones de seguridad?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (77, '¿Existe un procedimiento formal para el archivado y depuración (purga de datos) en el ERP para mantener el rendimiento técnico?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (78, '¿El proceso de depuración y archivado cumple estrictamente con los plazos legales y regulatorios de retención de información?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (79, '¿Se mantiene la posibilidad de consultar datos históricos archivados sin degradar el desempeño transaccional del entorno de producción?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (80, '¿Existe una conciliación automatizada para validar la integridad de las interfaces contables que alimentan al ERP desde sistemas periféricos?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
    (81, '¿El ERP dispone de alertas automáticas para notificar anomalías transaccionales o múltiples intentos fallidos de acceso a seguridad?', '6. Cumplimiento, Trazabilidad de Datos y Otros Elementos de Valor'),
]

def system_erp_criteria() -> list[dict]:
    return [
        {
            "code": f"TI{i:03d}",
            "text": q,
            "weight": 1,
            "source_id": i,
            "section": sec,
            "evaluation_mode": "ERP_TI",
        }
        for i, q, sec in SYSTEM_ERP_CONTROLS
    ]


def validate_criteria(criteria) -> list[dict]:
    """Valida criterios editados por el Contralor.

    Las cédulas operativas conservan el límite histórico de 40 criterios.
    El cuestionario oficial de Auditoría de Sistemas / ERP-TI contiene 81
    controles, por lo que ese tipo de cédula admite hasta 120 controles.
    """
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("Debe existir al menos un criterio")
    is_system = any(isinstance(c, dict) and c.get("evaluation_mode") == "ERP_TI" for c in criteria)
    max_items = 120 if is_system else 40
    if len(criteria) > max_items:
        raise ValueError(f"La cédula admite como máximo {max_items} criterios")
    seen, out = set(), []
    for c in criteria:
        if not isinstance(c, dict):
            raise ValueError("Criterio inválido")
        code, text, weight = str(c.get("code", "")).strip().upper(), str(c.get("text", "")).strip(), c.get("weight", 1)
        if not (2 <= len(code) <= 6 and code.isalnum()):
            raise ValueError(f"Código inválido: {code!r} (2 a 6 letras o números)")
        if code in seen:
            raise ValueError(f"Código repetido: {code}")
        if not 5 <= len(text) <= 300:
            raise ValueError(f"{code}: el texto debe tener entre 5 y 300 caracteres")
        if weight not in (1, 2, 3):
            raise ValueError(f"{code}: el peso debe ser 1, 2 o 3")
        seen.add(code)
        item = {"code": code, "text": text, "weight": weight}
        for key in ("source_id", "section", "evaluation_mode"):
            if key in c and c[key] is not None:
                item[key] = c[key]
        out.append(item)
    return out
