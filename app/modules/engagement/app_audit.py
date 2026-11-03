"""Auditoría de aplicativos (sistemas lógicos): plantilla AcselX, encuestas direccionadas y evaluación (lógica pura).

Fuente: «Auditoria_TI_Sistema_AcselX_Matriz_Integrada_v2.xlsx» (Contraloría). Se conservan sus 30 controles en 6
bloques, la fórmula de la hoja «Cuestionario AcselX» (No = 0; Sí = 40 % + 30 % si existe evidencia + 30 % si está
actualizada o 15 % si está desactualizada; CONFORME solo con Sí + evidencia + actualizada), el diagnóstico por bloque
del «Dashboard» (>= 80 % satisfactorio, >= 50 % requiere mejora, menos crítico), la «Matriz de Riesgos»
(probabilidad x impacto: >= 15 crítico, >= 10 alto, >= 5 medio), las 12 pruebas técnicas, la «Trazabilidad SUDEASEG»
y la madurez COBIT/CMMI del «Informe y Hallazgos».

Encuesta direccionada: cada control se dirige al área que debe responderlo y se redacta en segunda persona, con la
evidencia que debe adjuntar y, cuando el control es medible, el dato que debe informar (minutos, horas, fecha o
cantidad). El dato se contrasta con los parámetros del aplicativo (RPO, RTO, frecuencia de pruebas): si contradice la
respuesta, la fila queda marcada como inconsistente para que el auditor la valide.
"""
from __future__ import annotations

from datetime import date, datetime

# ------------------------------------------------------------------ áreas destinatarias de la encuesta
AREAS = {
    "SEGURIDAD_TI": "Seguridad de la información / Seguridad TI",
    "DBA": "Administración de base de datos (DBA)",
    "DESARROLLO_QA": "Desarrollo y aseguramiento de calidad (QA)",
    "INFRAESTRUCTURA": "Infraestructura y continuidad operativa",
    "USUARIO_CLAVE": "Usuario clave / dueño del proceso",
    "CONTABILIDAD": "Contabilidad",
    "ACTUARIAL": "Área técnica y actuarial",
    "CUMPLIMIENTO": "Cumplimiento normativo",
}

BLOCKS = {
    "SEG": "1. Accesos, privilegios y segregación",
    "LOG": "2. Trazabilidad y audit trail",
    "BDD": "3. Criptografía y base de datos",
    "CHG": "4. Gestión de cambios y QA",
    "BCP": "5. Continuidad y DRP",
    "REG": "6. Integridad financiera y SUDEASEG",
}

CATEGORIES = {"CORE": "Sistema core del negocio", "ERP": "ERP administrativo", "CONTABLE": "Contable / financiero",
              "NOMINA": "Nómina y RRHH", "CANAL": "Canal digital / portal", "OTRO": "Otro"}
MODELS = {"PROPIO": "Desarrollo propio (in-house)", "TERCERIZADO": "Licenciado con soporte del fabricante",
          "SAAS": "SaaS (servicio en la nube del proveedor)", "NUBE": "Alojado en nube propia (IaaS/PaaS)"}
CRITICALITY = {"ALTA": "Alta", "MEDIA": "Media", "BAJA": "Baja"}

# Parámetros del aplicativo con los que se evalúan los datos medibles (editables en el inventario).
DEFAULT_PARAMS = {"rpo_min": 15, "rto_h": 4, "failover_months": 6, "log_review_days": 31}
PARAM_LABEL = {"rpo_min": "RPO objetivo (minutos)", "rto_h": "RTO objetivo (horas)",
               "failover_months": "Frecuencia máxima de prueba de conmutación (meses)",
               "log_review_days": "Antigüedad máxima de la revisión de bitácoras (días)"}

# ------------------------------------------------------------------ plantilla AcselX
# (código, código Excel, bloque, área, pregunta original, pregunta dirigida, evidencia, normas, dato medible)
# dato: None | (tipo, etiqueta, unidad, parámetro u objetivo, comparación)
ACSELX_CONTROLS = [
    ("SEG01", "SEG-ACX-01", "SEG", "SEGURIDAD_TI",
     "¿El gestor de autenticación de Acsel/x restringe el acceso concurrente permitiendo una única sesión activa simultánea por cada credencial?",
     "¿Su configuración de Acsel/x impide que una misma credencial mantenga más de una sesión activa a la vez?",
     "Configuración de parámetros de sesión en base de datos.", ("ISO-A.8.5", "COBIT-DSS05.04"), None),
    ("SEG02", "SEG-ACX-02", "SEG", "SEGURIDAD_TI",
     "¿El sistema fuerza el cambio obligatorio de contraseña en el primer inicio de sesión tras el provisionamiento o reseteo?",
     "¿Acsel/x obliga a cambiar la contraseña en el primer inicio de sesión después de crear el usuario o reiniciar su clave?",
     "Política de contraseñas parametrizada en Acsel/x.", ("ISO-A.5.17", "ISO-A.8.5"), None),
    ("SEG03", "SEG-ACX-03", "SEG", "DBA",
     "¿Se encuentran inhabilitadas o eliminadas las cuentas técnicas o genéricas (ej. test, demo, soporte) en el ambiente de producción?",
     "¿Tiene inhabilitadas o eliminadas todas las cuentas técnicas o genéricas (test, demo, soporte) en producción? Indique cuántas siguen activas.",
     "Listado activo de usuarios de BD contrastado con organigrama.", ("ISO-A.5.16", "ISO-A.5.18", "COBIT-DSS05.04"),
     ("NUMERO", "Cuentas genéricas o técnicas activas en producción", "cuentas", 0, "<=")),
    ("SEG04", "SEG-ACX-04", "SEG", "SEGURIDAD_TI",
     "¿La asignación de permisos de anulación de recibos y notas de crédito está segregada técnicamente de la emisión comercial?",
     "¿Los perfiles que anulan recibos y notas de crédito están separados técnicamente de los que emiten (ningún usuario tiene ambos)?",
     "Matriz de roles y permisos vs. flujograma operativo.", ("ISO-A.5.3", "ISO-A.5.15", "ISO-A.5.18", "VE-LAA"), None),
    ("SEG05", "SEG-ACX-05", "SEG", "SEGURIDAD_TI",
     "¿El módulo de administración de Acsel/x registra y alerta de forma automatizada cuando un usuario intenta acceder a opciones no autorizadas?",
     "¿Recibe su área una alerta automática cuando un usuario intenta entrar a una opción de Acsel/x que no tiene autorizada?",
     "Bitácora de eventos de seguridad (security log) del aplicativo.", ("ISO-A.8.15", "ISO-A.8.16"), None),
    ("LOG01", "LOG-ACX-01", "LOG", "DBA",
     "¿El Audit Trail de Acsel/x almacena de forma inalterable la IP, estación de trabajo y usuario exacto que originó cada transacción financiera?",
     "¿La pista de auditoría de Acsel/x guarda, sin posibilidad de modificarla, el usuario, la IP y la estación de cada transacción financiera?",
     "Muestra de consulta SQL sobre tablas de auditoría transaccional.", ("ISO-A.8.15", "COBIT-DSS05.07", "SUDEASEG-TI"), None),
    ("LOG02", "LOG-ACX-02", "LOG", "SEGURIDAD_TI",
     "¿Las bitácoras de eventos del sistema Acsel/x se replican o envían en tiempo real hacia un servidor centralizado SIEM externo?",
     "¿Las bitácoras de Acsel/x se envían en tiempo real a un SIEM o servidor centralizado fuera del propio aplicativo?",
     "Configuración de exportación/syslog hacia servidor centralizado.", ("ISO-A.8.15", "ISO-A.8.16", "COBIT-DSS05.07"), None),
    ("LOG03", "LOG-ACX-03", "LOG", "DBA",
     "¿Existe un procedimiento automatizado que impida la sobreescritura de los archivos de registro histórico antes del plazo normativo?",
     "¿Un procedimiento automático impide sobrescribir o borrar las bitácoras históricas antes del plazo de retención exigido?",
     "Política de retención de respaldos y permisos de almacenamiento.", ("ISO-A.8.15", "ISO-A.5.33"), None),
    ("LOG04", "LOG-ACX-04", "LOG", "DBA",
     "¿Acsel/x genera alertas automáticas ante modificaciones directas de parámetros financieros o tablas maestras fuera de horario laboral?",
     "¿Recibe una alerta automática si alguien modifica parámetros financieros o tablas maestras de Acsel/x fuera del horario laboral?",
     "Reglas de alerta en motor de BD o gestor de eventos.", ("ISO-A.8.16", "COBIT-DSS06.02"), None),
    ("LOG05", "LOG-ACX-05", "LOG", "SEGURIDAD_TI",
     "¿Se realiza un análisis formal mensual de las excepciones y errores registrados en las trazas de comunicación entre Acsel/x y APIs externas?",
     "¿Su área revisa cada mes, con acta firmada, los errores y excepciones de la comunicación entre Acsel/x y las API externas? Indique la fecha de la última revisión.",
     "Actas de revisión de logs firmadas por Seguridad de TI.", ("ISO-A.8.15", "COBIT-DSS05.07"),
     ("FECHA", "Fecha de la última revisión de bitácoras", "fecha", "log_review_days", "dias")),
    ("BDD01", "BDD-ACX-01", "BDD", "DBA",
     "¿Las llaves de cifrado criptográfico (Master Key) de la base de datos de Acsel/x se almacenan en un repositorio segregado (Key Vault)?",
     "¿Las llaves maestras de cifrado de la base de datos de Acsel/x se guardan en un repositorio separado (Key Vault o HSM)?",
     "Arquitectura de gestión de llaves y certificados de BD.", ("ISO-A.8.24",), None),
    ("BDD02", "BDD-ACX-02", "BDD", "DBA",
     "¿Se aplica enmascaramiento dinámico de datos (Dynamic Data Masking) en datos bancarios y cédulas para perfiles de consulta general?",
     "¿Los perfiles de consulta general ven enmascarados los datos bancarios y las cédulas de identidad?",
     "Definición de políticas de enmascaramiento en el esquema de BD.", ("ISO-A.8.11", "ISO-A.8.24", "VE-CRBV-28"), None),
    ("BDD03", "BDD-ACX-03", "BDD", "DBA",
     "¿Las conexiones de la aplicación Acsel/x hacia la base de datos se ejecutan obligatoriamente bajo canales cifrados (TLS 1.3 / SSL)?",
     "¿Todas las conexiones de Acsel/x a la base de datos viajan cifradas (TLS 1.2 o superior)?",
     "Archivo de configuración de cadenas de conexión (connection strings).", ("ISO-A.8.24", "ISO-A.8.20"), None),
    ("BDD04", "BDD-ACX-04", "BDD", "DBA",
     "¿Se encuentran bloqueados y sin permisos de ejecución los procedimientos almacenados de sistema no utilizados en la BD de Acsel/x?",
     "¿Tiene bloqueados y sin permiso de ejecución los procedimientos almacenados del sistema que Acsel/x no usa?",
     "Script de auditoría de permisos sobre procedimientos del sistema.", ("ISO-A.8.9", "ISO-A.8.2"), None),
    ("BDD05", "BDD-ACX-05", "BDD", "DBA",
     "¿El tablespace/filegroup donde residen los datos financieros de Acsel/x posee cuotas separadas de los espacios temporales (tempdb)?",
     "¿El espacio (tablespace/filegroup) de los datos financieros tiene cuota separada de los espacios temporales?",
     "Reporte de distribución de almacenamiento y propiedades de tablespaces.", ("ISO-A.8.6",), None),
    ("CHG01", "CHG-ACX-01", "CHG", "DESARROLLO_QA",
     "¿Existe un repositorio centralizado de control de versiones (ej. Git) para todo el código fuente y scripts aplicados a Acsel/x?",
     "¿Todo el código fuente y los scripts que se aplican a Acsel/x están en un repositorio de versiones centralizado (por ejemplo, Git)?",
     "Historial de commits y control de ramas en el repositorio corporativo.", ("ISO-A.8.4", "ISO-A.8.32", "COBIT-BAI06"), None),
    ("CHG02", "CHG-ACX-02", "CHG", "DESARROLLO_QA",
     "¿El ambiente de pruebas (Staging/QA) de Acsel/x cuenta con una estructura de datos anonimizada idéntica a Producción?",
     "¿Su ambiente de pruebas (QA) tiene la misma estructura que producción, con los datos personales anonimizados?",
     "Certificación de proceso de anonimización de datos en QA.", ("ISO-A.8.31", "ISO-A.8.33", "ISO-A.8.11"), None),
    ("CHG03", "CHG-ACX-03", "CHG", "DESARROLLO_QA",
     "¿Se ejecutan pruebas unitarias de regresión automatizadas sobre cálculos de primas y comisiones antes de aprobar pases a producción?",
     "¿Antes de cada pase a producción ejecuta pruebas automáticas de regresión sobre el cálculo de primas y comisiones?",
     "Reporte de ejecución de pruebas automatizadas adjunto a la RFC.", ("ISO-A.8.29", "ISO-A.8.32", "COBIT-BAI06", "SUDEASEG-CAMBIOS"), None),
    ("CHG04", "CHG-ACX-04", "CHG", "USUARIO_CLAVE",
     "¿El plan de despliegue de cambios contempla una ventana de validación funcional post-pase obligatoria por el usuario clave?",
     "¿Después de cada pase a producción, usted valida el cambio en una ventana definida y firma el acta de conformidad?",
     "Acta de aceptación y conformidad de liberación firmada por el usuario.", ("ISO-A.8.32", "COBIT-BAI07"), None),
    ("CHG05", "CHG-ACX-05", "CHG", "DESARROLLO_QA",
     "¿Se realiza una revisión de vulnerabilidades de código (SAST) en los componentes desarrollados a la medida e integrados con Acsel/x?",
     "¿Analiza con una herramienta de revisión de código (SAST) los desarrollos a la medida que se integran con Acsel/x antes de implantarlos?",
     "Reporte de análisis estático de código previo a implementación.", ("ISO-A.8.28", "ISO-A.8.29", "ISO-A.8.8"), None),
    ("BCP01", "BCP-ACX-01", "BCP", "INFRAESTRUCTURA",
     "¿Los respaldos transaccionales (transaction logs) de la BD de Acsel/x se ejecutan con frecuencia no mayor a 15 minutos (RPO)?",
     "¿Cada cuántos minutos respalda los registros transaccionales (transaction logs) de la base de datos de Acsel/x?",
     "Programación de tareas (Job scheduler) de respaldos de logs en BD.", ("ISO-A.8.13", "COBIT-DSS04.07"),
     ("NUMERO", "Frecuencia del respaldo de logs transaccionales", "minutos", "rpo_min", "<=")),
    ("BCP02", "BCP-ACX-02", "BCP", "INFRAESTRUCTURA",
     "¿Los medios de respaldo externos o en la nube de Acsel/x están inmutables y protegidos contra ransomware (WORM)?",
     "¿Sus copias de respaldo externas o en la nube son inmutables (WORM) y están protegidas contra ransomware?",
     "Configuración de políticas de inmutabilidad en el almacenamiento.", ("ISO-A.8.13", "ISO-A.8.7"), None),
    ("BCP03", "BCP-ACX-03", "BCP", "INFRAESTRUCTURA",
     "¿Se realizan pruebas semestrales de conmutación por error (Failover) hacia el sitio de respaldo secundario (DRP) de Acsel/x?",
     "¿Prueba al menos cada seis meses la conmutación (failover) de Acsel/x al sitio alterno? Indique la fecha de la última prueba.",
     "Informe técnico de resultados del último simulacro de conmutación.", ("ISO-A.5.29", "ISO-A.5.30", "COBIT-DSS04", "SUDEASEG-CONTINUIDAD"),
     ("FECHA", "Fecha de la última prueba de conmutación", "fecha", "failover_months", "meses")),
    ("BCP04", "BCP-ACX-04", "BCP", "INFRAESTRUCTURA",
     "¿El tiempo de restablecimiento de Acsel/x medido en las pruebas de restauración cumple estrictamente con el RTO menor a 4 horas?",
     "En la última prueba de restauración, ¿cuántas horas tardó en restablecer Acsel/x?",
     "Acta de tiempos cronometrados en la última prueba de DRP.", ("ISO-A.5.30", "COBIT-DSS04"),
     ("NUMERO", "Tiempo de restablecimiento medido", "horas", "rto_h", "<=")),
    ("BCP05", "BCP-ACX-05", "BCP", "INFRAESTRUCTURA",
     "¿Existe un procedimiento documentado y validado para la reconstrucción limpia de la infraestructura de Acsel/x (Bare-Metal Recovery)?",
     "¿Tiene documentado y probado el procedimiento para reconstruir desde cero la infraestructura de Acsel/x (bare-metal recovery)?",
     "Manual técnico de recuperación de infraestructura actualizado.", ("ISO-A.5.30", "ISO-A.8.13"), None),
    ("REG01", "REG-ACX-01", "REG", "ACTUARIAL",
     "¿El motor de cálculo de reservas técnicas en Acsel/x está parametrizado conforme a las metodologías actuariales vigentes de SUDEASEG?",
     "¿El cálculo de reservas técnicas en Acsel/x está parametrizado según las notas técnicas y metodologías aprobadas por la SUDEASEG?",
     "Dictamen actuarial y manual de parametrización de reservas.", ("SUDEASEG-RESERVAS", "VE-LAA", "COBIT-MEA03"), None),
    ("REG02", "REG-ACX-02", "REG", "CONTABILIDAD",
     "¿Las interfaces contables nocturnas de Acsel/x hacia el ERP generan un informe automático de conciliación de descuadres?",
     "¿Recibe cada mañana un informe automático de conciliación de la interfaz contable nocturna entre Acsel/x y el ERP?",
     "Reporte histórico de conciliación contable automática.", ("SUDEASEG-CONTABLE", "COBIT-DSS06.02"), None),
    ("REG03", "REG-ACX-03", "REG", "USUARIO_CLAVE",
     "¿El sistema Acsel/x bloquea la emisión de pólizas a intermediarios cuya licencia ante la SUDEASEG se encuentre suspendida?",
     "¿Acsel/x le impide emitir pólizas con intermediarios cuya autorización ante la SUDEASEG esté suspendida o vencida?",
     "Matriz de validación de estatus en maestro de agentes.", ("VE-LAA", "SUDEASEG-INTERMEDIARIOS", "COBIT-MEA03"), None),
    ("REG04", "REG-ACX-04", "REG", "USUARIO_CLAVE",
     "¿Existe un mecanismo técnico que impida la modificación manual de montos de siniestros una vez liquidados contablemente?",
     "Una vez liquidado contablemente un siniestro, ¿el sistema le impide modificar su monto manualmente?",
     "Prueba de restricciones de edición sobre tablas de liquidación.", ("COBIT-DSS06.02", "SUDEASEG-CONTABLE"), None),
    ("REG05", "REG-ACX-05", "REG", "CUMPLIMIENTO",
     "¿Los reportes regulatorios requeridos por la SUDEASEG generados por Acsel/x cuentan con firma digital o hash de integridad?",
     "¿Los reportes que Acsel/x genera para la SUDEASEG salen con firma digital o con un hash que permita verificar su integridad?",
     "Procedimiento de exportación y verificación de hash regulatorios.", ("VE-LMDFE", "SUDEASEG-ELECTRONICO", "ISO-A.5.34"), None),
]

# Matriz de riesgos: (código, categoría, descripción, control, prob/impacto si conforme, prob/impacto si no, normas)
ACSELX_RISKS = [
    ("RIE-ACX-01", "Segregación de funciones", "Accesos no autorizados o acumulación de funciones incompatibles en Acsel/x que permitan la creación/modificación de pólizas y fraudes operativos.", "SEG04", (2, 3), (4, 5), "SUDEASEG LAA / ISO 27001 (A.5.15, A.5.18)"),
    ("RIE-ACX-02", "Seguridad de accesos", "Ataques de fuerza bruta, cuentas genéricas activas o suplantación de identidad por ausencia de controles estrictos de inicio de sesión.", "SEG03", (1, 2), (4, 4), "ISO 27001 (A.5.17, A.8.5) / COBIT DSS05.04"),
    ("RIE-ACX-03", "Auditoría y trazabilidad", "Imposibilidad de imputar acciones maliciosas o no autorizadas sobre datos críticos debido a la alteración o ausencia de bitácoras centralizadas.", "LOG02", (1, 2), (4, 5), "SUDEASEG / COBIT DSS05.07 / ISO 27001 (A.8.15)"),
    ("RIE-ACX-04", "Confidencialidad de datos", "Fuga, exposición o acceso indebido a datos personales y bancarios de asegurados almacenados sin cifrado ni enmascaramiento.", "BDD02", (2, 3), (5, 5), "ISO 27001 (A.8.24) / CRBV art. 28 (habeas data)"),
    ("RIE-ACX-05", "Continuidad operativa", "Interrupción prolongada de la operación y pérdida irreversible de transacciones por fallas en respaldos o DRP no probados.", "BCP03", (1, 2), (4, 5), "SUDEASEG / COBIT DSS04 / ISO 27001 (A.5.29)"),
    ("RIE-ACX-06", "Gestión de cambios", "Corrupción de datos en producción, indisponibilidad del sistema o fallas de funcionalidad por despliegue de cambios sin pruebas automatizadas.", "CHG03", (1, 2), (4, 4), "COBIT BAI06 / ISO 27001 (A.8.25, A.8.32)"),
    ("RIE-ACX-07", "Integridad de interfaces", "Descalce de saldos, registros duplicados o pérdidas financieras en el procesamiento diferido de interfaces entre Acsel/x y el ERP contable.", "REG02", (1, 2), (3, 4), "COBIT DSS06.02 / Controles financieros internos"),
    ("RIE-ACX-08", "Cumplimiento regulatorio", "Sanciones administrativas o fiscales dictadas por la SUDEASEG por emisión con intermediarios suspendidos o reportes no verificados.", "REG03", (1, 2), (4, 5), "Marco regulador SUDEASEG / COBIT MEA03"),
]

# Pruebas técnicas sustantivas: (código, programa, área de evaluación, procedimiento, criterio/consulta, estándar)
ACSELX_TESTS = [
    ("PST-BD-01", "BD", "Control de accesos DBA", "Verificar usuarios con privilegios administrativos absolutos (sysadmin, SYSDBA) en BD para asegurar asignación exclusiva a DBAs autorizados.", "Consultar sys.server_principals o DBA_USERS/DBA_ROLE_PRIVS.", "ISO 27001 A.5.18"),
    ("PST-BD-02", "BD", "Cifrado en reposo (TDE)", "Comprobar técnicamente si el motor tiene habilitado cifrado transparente (TDE) o cifrado de columnas sensibles.", "Ejecutar comandos de verificación de estado de cifrado de tablespaces.", "SUDEASEG / ISO 27001"),
    ("PST-BD-03", "BD", "Audit trail de BD", "Verificar políticas de auditoría nativa activas registrando inicios de sesión y cambios DDL/DML en tablas transaccionales.", "Inspeccionar objetos de auditoría activos (sys.dm_audit_actions).", "COBIT DSS05.07"),
    ("PST-BD-04", "BD", "Consistencia transaccional", "Ejecutar cruce de datos entre tablas de emisión/siniestros y movimientos contables para detectar registros huérfanos o backdoors.", "Consulta SQL de conciliación de saldos sin contrapartida válida.", "Control financiero"),
    ("PST-BD-05", "BD", "Validación de respaldos", "Revisar ejecución de respaldos full/log y verificar mediante pruebas de restauración en QA la integridad (checksum).", "Inspeccionar historial en msdb/RMAN y actas de prueba de restauración.", "ISO 27001 A.5.29"),
    ("PST-BD-06", "BD", "Cuentas de servicio", "Auditar cadenas de conexión en archivos de configuración de Acsel/x para asegurar que no usen superusuarios y tengan rotación.", "Revisar bitácoras de conexiones activas y credenciales dedicadas.", "COBIT DSS05.04"),
    ("INT-CON-01", "INTERFAZ", "Canal de integración", "Verificar que la transferencia de asientos entre Acsel/x y ERP use canales cifrados (mTLS, SFTP con SSH key).", "Inspección de archivos web.config, scripts e interfaces.", "ISO 27001 A.8.24"),
    ("INT-CON-02", "INTERFAZ", "Checksum y totales", "Comprobar si la interfaz genera un bloque de control (batch control total) validando que débitos/créditos coincidan.", "Comparativa de logs de exportación Acsel/x vs importación ERP.", "COBIT DSS06.02"),
    ("INT-CON-03", "INTERFAZ", "Registros huérfanos", "Ejecutar script de cruce entre transacciones de Acsel/x y el ERP para detectar asientos sin contrapartida o duplicados.", "Consulta SQL de conciliación por número de póliza/comprobante.", "COBIT BAI06"),
    ("INT-CON-04", "INTERFAZ", "Cola de errores", "Auditar la tabla/directorio de errores para comprobar si transacciones rechazadas generan alertas sin perderse.", "Revisión de repositorio de excepciones y tickets de corrección.", "SUDEASEG"),
    ("INT-CON-05", "INTERFAZ", "Edición post-interfaz", "Verificar que los asientos generados automáticamente por la interfaz no puedan ser editados manualmente en el ERP.", "Inspección de perfiles ERP y journal audit log.", "ISO 27001 A.5.18"),
    ("INT-CON-06", "INTERFAZ", "Conversión de moneda", "Evaluar si las conversiones monetarias y tasas aplicadas en Acsel/x coinciden exactamente con las del ERP.", "Cruce de muestra de transacciones en divisa extranjera.", "Normativa contable"),
]
TEST_PROGRAMS = {"BD": "Pruebas sustantivas sobre la base de datos", "INTERFAZ": "Interfaz y conciliación contable (aplicativo - ERP)"}
TEST_RESULTS = {"CUMPLE": "Cumple", "NO_CUMPLE": "No cumple", "NO_APLICA": "No aplica", "PENDIENTE": "Pendiente"}

# Trazabilidad regulatoria: (código, área, marco regulatorio, requerimiento, control, estándar internacional)
ACSELX_TRACE = [
    ("TRAZ-01", "Seguridad de accesos", "Ley de la Actividad Aseguradora y providencias de control interno", "Obligatoriedad de mantener esquemas formales de autorización, segregación de funciones (SoD) y control estricto sobre perfiles de escritura.", "SEG04", "ISO 27001 (A.5.15, A.5.18) / COBIT DSS05.04"),
    ("TRAZ-02", "Integridad transaccional", "Normas SUDEASEG sobre tecnología de la información", "Exigencia de contar con pistas de auditoría inalterables que registren el ciclo de vida completo de cada transacción.", "LOG01", "ISO 27001 (A.8.15) / COBIT DSS05.07"),
    ("TRAZ-03", "Protección de datos", "Confidencialidad de tomadores y asegurados (CRBV art. 28)", "Deber de salvaguardar la privacidad y los datos de tomadores y asegurados mediante controles criptográficos y de acceso estricto.", "BDD02", "ISO 27001 (A.8.24) / COBIT DSS05.02"),
    ("TRAZ-04", "Continuidad de negocio", "Lineamientos de BCP/DRP y gestión de riesgo operacional", "Obligación de garantizar la disponibilidad de los sistemas misionales mediante respaldos periódicos y pruebas formales de DRP.", "BCP03", "ISO 27001 (A.5.29) / COBIT DSS04"),
    ("TRAZ-05", "Gestión de cambios", "Normas sobre control de cambios en sistemas aplicativos", "Requisito de mantener ambientes segregados (QA/producción) con autorización formal de cambios (RFC) y pruebas.", "CHG03", "ISO 27001 (A.8.25) / COBIT BAI06"),
    ("TRAZ-06", "Integridad financiera", "Normativa contable de la SUDEASEG y presentación de balances", "Cuadre exacto, conciliación periódica y prohibición de asientos manuales no justificados entre el core técnico y contabilidad.", "REG02", "COBIT DSS06.02 / Control financiero"),
    ("TRAZ-07", "Parámetros actuariales", "Providencias sobre notas técnicas y reservas técnicas", "Cumplimiento estricto de las notas técnicas aprobadas: el software aplica fielmente las fórmulas actuariales registradas.", "REG01", "COBIT MEA03 / Controles regulatorios"),
]

# Madurez COBIT/CMMI por dominio: (clave, dominio, bloques que lo alimentan)
ACSELX_MATURITY = [
    ("DSS05", "DSS05: Accesos y privilegios", ("SEG",)),
    ("DSS05.07", "DSS05.07 / A.8.15: Trazabilidad", ("LOG",)),
    ("A.8.24", "A.8.24 / SUDEASEG: Cifrado de BD", ("BDD",)),
    ("BAI06", "BAI06: Gestión de cambios", ("CHG",)),
    ("DSS04", "DSS04 / A.5.29: Continuidad (BCP)", ("BCP",)),
    ("DSS06.02", "DSS06.02: Integridad financiera", ("REG",)),
]
MATURITY_NAMES = {0: "Inexistente", 1: "Inicial / Ad-hoc", 2: "Gestionado", 3: "Definido", 4: "Medible / Cuantitativo", 5: "Optimizado"}

TEMPLATES = {
    "ACSELX": {"title": "Auditoría TI del sistema Acsel/x", "category": "CORE", "controls": ACSELX_CONTROLS, "risks": ACSELX_RISKS,
               "tests": ACSELX_TESTS, "trace": ACSELX_TRACE, "maturity": ACSELX_MATURITY,
               "source": "Auditoria_TI_Sistema_AcselX_Matriz_Integrada_v2.xlsx"},
}
TEMPLATE_LABEL = {k: v["title"] for k, v in TEMPLATES.items()}


def template(code: str | None) -> dict:
    return TEMPLATES.get(str(code or "").upper()) or TEMPLATES["ACSELX"]


def criteria(code: str | None = "ACSELX", weights: dict | None = None) -> list[dict]:
    """Controles de la plantilla como criterios de la cédula de Sistemas (fórmula 40/30/30).

    weights: pesos aprobados por el Contralor a partir de las propuestas del motor ({código: 1..3}).
    """
    t = template(code)
    out = []
    for i, (code_, src, block, area, original, directed, evidence, norms, data) in enumerate(t["controls"], start=1):
        c = {"code": code_, "text": directed, "weight": int((weights or {}).get(code_, 1)), "source_id": src,
             "section": BLOCKS[block], "evaluation_mode": "ERP_TI", "block": block, "area": area,
             "original": original, "evidence_required": evidence, "norms": list(norms), "order": i}
        if data:
            kind, label, unit, target, op = data
            c["data"] = {"type": kind, "label": label, "unit": unit, "target": target, "op": op}
        out.append(c)
    return out


def params_of(profile: dict | None) -> dict:
    p = dict(DEFAULT_PARAMS)
    for k, v in ((profile or {}).get("params") or {}).items():
        if k in DEFAULT_PARAMS:
            try:
                p[k] = float(v) if "." in str(v) else int(v)
            except (TypeError, ValueError):
                pass
    return p


# ------------------------------------------------------------------ dato medible de la encuesta
def _as_date(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _as_number(v) -> float | None:
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def normalize_data(criterion: dict, value):
    """Valor del dato medible tal como se guarda (número o fecha ISO), o None si no aplica o es inválido."""
    spec = criterion.get("data")
    if not spec or value in (None, ""):
        return None
    if spec["type"] == "NUMERO":
        n = _as_number(value)
        return None if n is None or n < 0 else (int(n) if float(n).is_integer() else round(n, 2))
    d = _as_date(value)
    return d.isoformat() if d else None


def data_target(criterion: dict, params: dict):
    spec = criterion.get("data") or {}
    t = spec.get("target")
    return params.get(t, DEFAULT_PARAMS.get(t)) if isinstance(t, str) else t


def data_verdict(criterion: dict, value, params: dict, today: date | None = None) -> str | None:
    """'SI' si el dato cumple el objetivo, 'NO' si no, None si no hay dato."""
    spec = criterion.get("data")
    if not spec or value in (None, ""):
        return None
    target = data_target(criterion, params)
    if spec["type"] == "NUMERO":
        n = _as_number(value)
        if n is None or target is None:
            return None
        return "SI" if n <= float(target) else "NO"
    d = _as_date(value)
    if d is None or target is None:
        return None
    today = today or date.today()
    if d > today:
        return "NO"
    age_days = (today - d).days
    limit = float(target) * (30.44 if spec["op"] == "meses" else 1)
    return "SI" if age_days <= limit else "NO"


def describe_target(criterion: dict, params: dict) -> str:
    spec = criterion.get("data") or {}
    t = data_target(criterion, params)
    if not spec:
        return ""
    if spec["type"] == "NUMERO":
        return f"Objetivo: {spec['unit']} ≤ {t}"
    return f"Objetivo: no más de {t} {'meses' if spec['op'] == 'meses' else 'días'} de antigüedad"


def inconsistency(criterion: dict, result: dict, params: dict, today: date | None = None) -> str | None:
    """Mensaje si el dato informado contradice la respuesta Sí/No del control."""
    answer = str((result or {}).get("control") or "").upper()
    verdict = data_verdict(criterion, (result or {}).get("dato"), params, today)
    if verdict is None or answer not in ("SI", "NO") or verdict == answer:
        return None
    spec = criterion["data"]
    shown = (result or {}).get("dato")
    if answer == "SI":
        return (f"Respondió «Sí», pero el dato informado ({shown} {spec['unit'] if spec['type'] == 'NUMERO' else ''}".strip()
                + f") no cumple: {describe_target(criterion, params).lower()}.")
    return f"Respondió «No», pero el dato informado ({shown}) cumple el objetivo; confirme la respuesta."


# ------------------------------------------------------------------ evaluación (réplica del Excel)
def control_points(result: dict) -> float | None:
    """Puntaje 0-100 del control según la fórmula del Excel, o None si no se respondió."""
    r = result or {}
    control = str(r.get("control") or "").upper()
    if control not in ("SI", "NO"):
        return None
    if control == "NO":
        return 0.0
    pts = 40.0 + (30.0 if str(r.get("documental") or "").upper() == "SI" else 0.0)
    ev = str(r.get("evidencia") or "").upper()
    return pts + (30.0 if ev == "ACTUALIZADO" else 15.0 if ev == "DESACTUALIZADO" else 0.0)


def is_conforme(result: dict) -> bool:
    r = result or {}
    return (str(r.get("control") or "").upper() == "SI" and str(r.get("documental") or "").upper() == "SI"
            and str(r.get("evidencia") or "").upper() == "ACTUALIZADO")


def diagnosis(pct: float | None) -> str:
    if pct is None:
        return "Sin evaluar"
    return "Satisfactorio" if pct >= 80 else "Requiere mejora" if pct >= 50 else "Crítico"


def _results(items: list[dict]) -> dict:
    out = {}
    for it in items or []:
        r = (it.get("results") or {}).get(it.get("ref"))
        if isinstance(r, dict):
            out[it["ref"]] = r
    return out


def block_summary(criteria_: list[dict], items: list[dict]) -> list[dict]:
    """Cumplimiento por bloque (hoja Dashboard): conformes / total y promedio de la fórmula."""
    res = _results(items)
    rows = []
    for key, label in BLOCKS.items():
        codes = [c["code"] for c in criteria_ if c.get("block") == key]
        if not codes:
            continue
        conf = sum(1 for c in codes if is_conforme(res.get(c)))
        answered = [control_points(res.get(c)) for c in codes]
        answered = [p for p in answered if p is not None]
        pct_conf = round(100.0 * conf / len(codes), 1)
        rows.append({"block": key, "label": label, "total": len(codes), "conformes": conf, "hallazgos": len(codes) - conf,
                     "answered": len(answered), "cumplimiento": pct_conf,
                     "promedio": round(sum(answered) / len(answered), 1) if answered else None,
                     "diagnostico": diagnosis(pct_conf if answered else None)})
    return rows


def overview(criteria_: list[dict], items: list[dict], params: dict | None = None, today: date | None = None) -> dict:
    """Panel de control de respuestas (cabecera de la hoja Cuestionario)."""
    res = _results(items)
    params = params or DEFAULT_PARAMS
    pts = [control_points(res.get(c["code"])) for c in criteria_]
    scored = [p for p in pts if p is not None]
    conf = sum(1 for c in criteria_ if is_conforme(res.get(c["code"])))
    total = len(criteria_)
    incons = [{"code": c["code"], "message": m} for c in criteria_
              if (m := inconsistency(c, res.get(c["code"]) or {}, params, today))]
    by_area = {}
    for c in criteria_:
        a = c.get("area") or "OTRO"
        row = by_area.setdefault(a, {"area": a, "label": AREAS.get(a, a), "total": 0, "answered": 0})
        row["total"] += 1
        row["answered"] += 1 if control_points(res.get(c["code"])) is not None else 0
    return {"total": total, "respuestas_si": sum(1 for c in criteria_ if str((res.get(c["code"]) or {}).get("control") or "").upper() == "SI"),
            "conformes": conf, "hallazgos": total - conf,
            "cumplimiento_efectivo": round(100.0 * conf / total, 1) if total else None,
            "promedio_general": round(sum(scored) / len(scored), 1) if scored else None,
            "elaborados": sum(1 for c in criteria_ if str((res.get(c["code"]) or {}).get("documental") or "").upper() == "SI"),
            "pendientes": total - len(scored), "inconsistencias": incons, "areas": list(by_area.values())}


def risk_level(score: int) -> str:
    return "Crítico" if score >= 15 else "Alto" if score >= 10 else "Medio" if score >= 5 else "Bajo"


def risk_matrix(code: str | None, items: list[dict], history: dict | None = None, overrides: dict | None = None) -> list[dict]:
    """Matriz de riesgos: probabilidad e impacto según el estado del control, ajustados por el historial y por el Jefe.

    history: {control: {"delta": -1..+1, "reason": str}} (retroalimentación del motor).
    overrides: {riesgo: {"probability", "impact", "reason", "by_name"}} (decisión humana; prevalece).
    """
    res = _results(items)
    out = []
    for rc, cat, desc, ctrl, ok, bad, frame in template(code)["risks"]:
        r = res.get(ctrl)
        answered = control_points(r) is not None
        conf = is_conforme(r)
        p, i = ok if conf else bad
        h = (history or {}).get(ctrl) or {}
        delta = int(h.get("delta") or 0)
        p_adj = max(1, min(5, p + delta))
        ov = (overrides or {}).get(rc)
        p_final, i_final = (int(ov["probability"]), int(ov["impact"])) if ov else (p_adj, i)
        score = p_final * i_final
        out.append({"code": rc, "category": cat, "description": desc, "control": ctrl, "framework": frame,
                    "control_state": "CONFORME" if conf else ("HALLAZGO DE AUDITORÍA" if answered else "SIN EVALUAR"),
                    "base_probability": p, "history_delta": delta, "history_reason": h.get("reason"),
                    "probability": p_final, "impact": i_final, "score": score, "level": risk_level(score),
                    "status": "Mitigado / controlado" if conf else ("RIESGO MATERIALIZADO" if answered else "Sin evaluar"),
                    "override": ov})
    return out


def maturity(code: str | None, criteria_: list[dict], items: list[dict], overrides: dict | None = None) -> list[dict]:
    """Madurez COBIT/CMMI sugerida por dominio a partir del promedio del bloque (el auditor la ajusta).

    Promedio de la fórmula: < 20 -> 0, < 40 -> 1, < 60 -> 2, < 80 -> 3, < 95 -> 4, >= 95 -> 5.
    """
    blocks = {b["block"]: b for b in block_summary(criteria_, items)}
    out = []
    for key, label, srcs in template(code)["maturity"]:
        vals = [blocks[s]["promedio"] for s in srcs if s in blocks and blocks[s]["promedio"] is not None]
        avg = round(sum(vals) / len(vals), 1) if vals else None
        level = None if avg is None else (0 if avg < 20 else 1 if avg < 40 else 2 if avg < 60 else 3 if avg < 80 else 4 if avg < 95 else 5)
        ov = (overrides or {}).get(key)
        final = int(ov["level"]) if ov else level
        state = (None if final is None else "Deficiente" if final <= 1 else "Parcialmente satisfactorio" if final == 2
                 else "Satisfactorio" if final == 3 else "Sólido")
        out.append({"key": key, "label": label, "average": avg, "suggested": level, "level": final,
                    "name": MATURITY_NAMES.get(final) if final is not None else "Sin evaluar", "state": state or "Sin evaluar",
                    "note": (ov or {}).get("note"), "override": ov})
    return out


def traceability(code: str | None, items: list[dict]) -> list[dict]:
    res = _results(items)
    out = []
    for tc, area, frame, req, ctrl, intl in template(code)["trace"]:
        r = res.get(ctrl)
        state = "CONFORME" if is_conforme(r) else ("HALLAZGO DE AUDITORÍA" if control_points(r) is not None else "SIN EVALUAR")
        out.append({"code": tc, "area": area, "framework": frame, "requirement": req, "control": ctrl,
                    "state": state, "international": intl})
    return out


def tests_view(code: str | None, recorded: dict | None = None) -> list[dict]:
    recorded = recorded or {}
    out = []
    for tc, prog, area, proc, crit, std in template(code)["tests"]:
        r = recorded.get(tc) or {}
        out.append({"code": tc, "program": prog, "program_label": TEST_PROGRAMS[prog], "area": area, "procedure": proc,
                    "criterion": crit, "standard": std, "result": r.get("result") or "PENDIENTE",
                    "detail": r.get("detail"), "query": r.get("query_used"), "evidence_id": r.get("evidence_id"),
                    "updated_by_name": r.get("updated_by_name"), "updated_at": r.get("updated_at")})
    return out


def tests_summary(tests: list[dict]) -> dict:
    counts = {k: sum(1 for t in tests if t["result"] == k) for k in TEST_RESULTS}
    done = counts["CUMPLE"] + counts["NO_CUMPLE"]
    return {**counts, "total": len(tests), "executed": done,
            "pct_cumple": round(100.0 * counts["CUMPLE"] / done, 1) if done else None}


def opinion(overview_: dict, risks: list[dict]) -> tuple[str, str]:
    """Dictamen sobre el entorno de control del aplicativo (hoja Informe y Hallazgos)."""
    crit = sum(1 for r in risks if r["level"] == "Crítico" and r["control_state"] != "SIN EVALUAR")
    pct = overview_.get("cumplimiento_efectivo")
    if pct is None or not overview_.get("total") or overview_.get("pendientes") == overview_.get("total"):
        return "SIN_DICTAMEN", "Dictamen pendiente: el cuestionario no tiene respuestas."
    if pct < 50 or crit >= 3:
        return "DESFAVORABLE", "OPINIÓN DESFAVORABLE (ADVERSA)"
    if crit or pct < 80:
        return "SALVEDADES", "OPINIÓN CON SALVEDADES (CONDICIONADA)"
    return "FAVORABLE", "OPINIÓN FAVORABLE (LIMPIA)"


def opinion_text(app_name: str, overview_: dict, risks: list[dict], blocks: list[dict]) -> str:
    key, _ = opinion(overview_, risks)
    low = lambda t: t[:1].lower() + t[1:]          # conserva siglas (QA, SUDEASEG, DRP)
    weak = [low(b["label"].split(". ", 1)[-1]) for b in blocks if b["diagnostico"] == "Crítico"]
    strong = [low(b["label"].split(". ", 1)[-1]) for b in blocks if b["diagnostico"] == "Satisfactorio"]
    crit = [low(r["category"]) for r in risks if r["level"] == "Crítico" and r["control_state"] == "HALLAZGO DE AUDITORÍA"]
    pct = overview_.get("cumplimiento_efectivo")
    join = lambda xs: xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]
    if key == "SIN_DICTAMEN":
        return f"El dictamen sobre {app_name} se emitirá cuando se complete el cuestionario."
    base = {"FAVORABLE": f"Se emite una OPINIÓN FAVORABLE sobre el entorno de control del sistema {app_name}",
            "SALVEDADES": f"Se emite una OPINIÓN CON SALVEDADES sobre el entorno de control del sistema {app_name}",
            "DESFAVORABLE": f"Se emite una OPINIÓN DESFAVORABLE sobre el entorno de control del sistema {app_name}"}[key]
    text = (f"{base}: {overview_['conformes']} de {overview_['total']} controles son conformes "
            f"({f'{pct:.1f}'.replace('.', ',')} % de cumplimiento efectivo).")
    if strong:
        text += f" {'Los bloques' if len(strong) > 1 else 'El bloque'} de {join(strong)} {'presentan' if len(strong) > 1 else 'presenta'} un nivel satisfactorio."
    if weak:
        text += f" {'Los bloques' if len(weak) > 1 else 'El bloque'} de {join(weak)} {'se encuentran' if len(weak) > 1 else 'se encuentra'} en nivel crítico."
    if crit:
        text += f" Se materializan riesgos críticos de {join(crit)}, que exponen a la institución a sanciones regulatorias y a riesgo de fraude."
    if key != "FAVORABLE":
        text += " La administración de TI debe ejecutar el plan de acción correctiva en los plazos acordados."
    return text


# ------------------------------------------------------------------ encuestas direccionadas por área
def survey_rows(criteria_: list[dict], area: str, items: list[dict] | None = None, params: dict | None = None) -> list[dict]:
    """Preguntas de la encuesta de un área, en el orden de la plantilla, con la respuesta vigente si existe."""
    res = _results(items or [])
    params = params or DEFAULT_PARAMS
    out = []
    for c in criteria_:
        if c.get("area") != area:
            continue
        r = res.get(c["code"]) or {}
        spec = c.get("data")
        out.append({"code": c["code"], "source_id": c.get("source_id"), "block": BLOCKS.get(c.get("block"), c.get("section")),
                    "question": c["text"], "evidence": c.get("evidence_required") or "",
                    "data_label": f"{spec['label']} ({spec['unit']})" if spec else "",
                    "data_type": spec["type"] if spec else None, "target": describe_target(c, params) if spec else "",
                    "control": r.get("control") or "", "documental": r.get("documental") or "", "evidencia": r.get("evidencia") or "",
                    "dato": r.get("dato"), "comment": r.get("comentario") or ""})
    return out


def areas_in(criteria_: list[dict]) -> list[dict]:
    seen = []
    for c in criteria_:
        a = c.get("area")
        if a and a not in seen:
            seen.append(a)
    return [{"area": a, "label": AREAS.get(a, a), "questions": sum(1 for c in criteria_ if c.get("area") == a)} for a in seen]


SURVEY_CONTROL = {"SI": "SI", "SÍ": "SI", "NO": "NO"}
SURVEY_EVIDENCE = {"ACTUALIZADO": "ACTUALIZADO", "ACTUALIZADA": "ACTUALIZADO", "DESACTUALIZADO": "DESACTUALIZADO",
                   "DESACTUALIZADA": "DESACTUALIZADO", "INEXISTENTE": "INEXISTENTE"}


def parse_survey_answer(criterion: dict, raw: dict) -> dict | None:
    """Respuesta de una fila de la encuesta (Excel) normalizada a la cédula, o None si está vacía."""
    def norm(v):
        import unicodedata
        s = unicodedata.normalize("NFKD", str(v or "").strip().upper())
        return "".join(ch for ch in s if not unicodedata.combining(ch))
    control = SURVEY_CONTROL.get(norm(raw.get("control")), "")
    doc = SURVEY_CONTROL.get(norm(raw.get("documental")), "")
    ev = SURVEY_EVIDENCE.get(norm(raw.get("evidencia")), "")
    dato = normalize_data(criterion, raw.get("dato"))
    comment = str(raw.get("comment") or "").strip()[:1000]
    if not (control or doc or ev or dato is not None or comment):
        return None
    if control == "NO":
        doc, ev = doc or "NO", ev or "INEXISTENTE"
    out = {"control": control, "documental": doc, "evidencia": ev}
    if dato is not None:
        out["dato"] = dato
    if comment:
        out["comentario"] = comment
    return out
