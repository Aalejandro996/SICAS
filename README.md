# SICAS V.1.2 — Sistema Integral de Contraloría y Auditoría de Seguros

**Plataforma de gestión, ejecución y control de auditorías para el sector asegurador venezolano.**

SICAS es una plataforma web diseñada para centralizar y estructurar el ciclo de auditoría de una compañía de seguros, desde la creación del expediente y la planificación hasta el trabajo de campo, la documentación de evidencias, la elaboración de informes y su revisión y aprobación.

La solución utiliza **Python, Flask, PostgreSQL, Celery, Redis y Docker**, con una arquitectura modular orientada a la trazabilidad, la segregación de funciones, la integridad de la información y la gestión controlada de los procesos de auditoría.

---

## Información general

| Campo | Descripción |
|---|---|
| Nombre | SICAS — Sistema Integral de Contraloría y Auditoría de Seguros |
| Versión | **V.1.2** |
| Sector | Asegurador |
| Ámbito de aplicación | Contraloría, auditoría interna, auditoría financiera y auditoría de Sistemas/TI |
| Backend | Python / Flask |
| Base de datos | PostgreSQL |
| Procesamiento asíncrono | Celery / Redis |
| Infraestructura | Docker / Docker Compose |
| Acceso web | HTTPS mediante Nginx |
| Estado | Versión en revisión y validación funcional y técnica |
| Responsable de elaboración | Adrian Muñoz — Auditor de Sistemas |

## 1. Objetivo del sistema

Proporcionar una plataforma centralizada para planificar, ejecutar, documentar y supervisar las auditorías de la aseguradora, facilitando la aplicación de criterios de control, la recopilación de evidencias, la identificación de excepciones y la elaboración de informes verificables.

SICAS busca mejorar la consistencia de los procedimientos de auditoría, fortalecer la trazabilidad de las actuaciones y facilitar la supervisión de los resultados por parte de los responsables autorizados.

## 2. Funcionalidades principales

### 2.1. Gestión de expedientes y auditorías

- Creación y administración de expedientes de auditoría.
- Asociación de auditorías con unidades, sucursales, procesos y períodos.
- Identificación de objetivos, alcance, responsables y equipos de trabajo.
- Configuración de auditorías remotas o presenciales.
- Organización del trabajo en las fases de **Planificación, Trabajo de campo e Informe**.
- Seguimiento de la documentación y los resultados asociados a cada auditoría.

### 2.2. Cédulas de auditoría financiera

SICAS contempla cédulas diferenciadas para los principales procesos de suscripción y reclamos o indemnizaciones:

| Proceso | Líneas de negocio |
|---|---|
| Suscripción | Auto, Patrimonial y Personal |
| Reclamos o indemnizaciones | Auto, Patrimonial y Personal |

Cada cédula organiza los criterios de evaluación y los ítems operativos correspondientes, permitiendo registrar resultados y vincularlos con el trabajo de auditoría.

La estructura permite mantener una relación entre las cédulas, sus criterios y los ítems evaluados.

### 2.3. Auditoría de Sistemas y Tecnología de la Información

La plataforma contempla un dominio específico para auditorías de Sistemas/TI, diferenciado de los procesos de auditoría financiera.

Su alcance funcional incluye áreas como:

- Sistemas y aplicaciones empresariales.
- Pruebas y certificaciones.
- Servidores y bases de datos.
- Redes y telecomunicaciones.
- Microinformática.
- Ciberseguridad.
- Gestión de Sistemas y Tecnología de la Información.

Este dominio está orientado a organizar cuestionarios, pruebas, resultados y evidencias técnicas. La cobertura definitiva depende de la validación del cuestionario institucional y de las pruebas de aceptación del módulo.

### 2.4. Evaluación, calificación y observaciones

- Registro de resultados por criterio o ítem.
- Evaluación de excepciones y desviaciones identificadas.
- Calificación de controles según las reglas configuradas.
- Capacidad prevista para ajustar manualmente una calificación por criterio del auditor, con justificación.
- Documentación de observaciones y hallazgos.
- Vinculación de evidencias con los resultados de auditoría.

Los ajustes manuales y su trazabilidad deben comprobarse mediante pruebas de aceptación que confirmen la identidad del usuario, la justificación, el historial y los permisos correspondientes.

### 2.5. Evidencias y documentación de auditoría

SICAS contempla la organización de los soportes que respaldan las pruebas y conclusiones, incluyendo:

- Documentos y archivos asociados a los expedientes.
- Evidencias vinculadas con criterios, ítems y observaciones.
- Documentación de excepciones en la recepción de información.
- Anexos de respaldo para los informes.
- Preparación de documentación para revisión y aprobación.

La disponibilidad, integridad, retención y recuperación de los archivos deben validarse en el entorno candidato a producción.

### 2.6. Informes y flujo de aprobación

El flujo funcional previsto comprende:

1. Creación del expediente.
2. Planificación de la auditoría.
3. Ejecución del trabajo de campo.
4. Registro de pruebas, resultados y evidencias.
5. Elaboración del informe.
6. Remisión a la unidad o sucursal correspondiente.
7. Revisión y control por los responsables autorizados.
8. Aprobación del Contralor, según el procedimiento aplicable.
9. Generación y conservación del informe final aprobado.

El alcance documental contempla la preparación de informes, anexos de evidencia y planes de acción correctiva (PAC), incluyendo archivos Excel cuando corresponda.

La generación definitiva, la firma electrónica, la impresión y las etapas exactas de aprobación deben verificarse frente al procedimiento institucional vigente.

## 3. Seguridad y control de acceso

La arquitectura de SICAS contempla controles destinados a proteger la información y restringir las operaciones según las responsabilidades de cada usuario.

### 3.1. Identidad y permisos

El modelo funcional contempla:

- Gestión de usuarios y roles.
- Control de acceso basado en roles (RBAC).
- Separación de responsabilidades entre auditores, responsables de auditoría, Contraloría y administración técnica.
- Diferenciación de permisos por dominio de auditoría.
- Restricción de operaciones según los permisos asignados.
- Controles de revisión y aprobación para operaciones sensibles.

Los perfiles especializados contemplados incluyen auditoría financiera y auditoría de Sistemas/TI, además de los roles generales de auditoría, Contraloría y administración.

La autenticación multifactor (MFA), el doble control y los mecanismos de sesión deben considerarse habilitados únicamente cuando su configuración y funcionamiento hayan sido comprobados en la versión desplegada.

### 3.2. Trazabilidad e integridad

El diseño técnico contempla un registro de auditoría de eventos, controles de integridad y mecanismos de verificación.

La documentación del proyecto también describe un esquema de integridad encadenada y anclaje firmado. Su efectividad debe confirmarse mediante pruebas de generación, verificación, protección contra alteraciones y recuperación de los registros.

### 3.3. Protección de la información

Para la operación institucional se recomienda:

- Uso obligatorio de HTTPS.
- Gestión segura de credenciales y secretos.
- Restricción de acceso a la base de datos y a los servicios internos.
- Separación de ambientes de desarrollo, pruebas y producción.
- Aplicación de privilegios mínimos.
- Copias de seguridad y pruebas de restauración.
- Registro de operaciones relevantes y revisión de accesos.

## 4. Arquitectura tecnológica

SICAS utiliza una arquitectura modular con servicios separados por responsabilidad.

| Componente | Responsabilidad |
|---|---|
| Flask | Lógica de aplicación y servicios HTTP/API |
| Gunicorn | Ejecución de la aplicación Python |
| PostgreSQL | Persistencia de información y relaciones de negocio |
| Redis | Cola y coordinación de tareas |
| Celery Worker | Ejecución de tareas asíncronas |
| Celery Beat | Programación de tareas periódicas |
| Nginx | Proxy inverso y punto de entrada HTTPS |
| Docker Compose | Coordinación de servicios y configuración del entorno |

### Flujo general de comunicación

El navegador del usuario se comunica con Nginx mediante HTTPS. Nginx reenvía las solicitudes a la API Flask/Gunicorn a través de la red interna de los contenedores.

La API valida los permisos y ejecuta las operaciones de negocio, consultando PostgreSQL cuando necesita leer o guardar información. Los procesos que requieren ejecución asíncrona pueden utilizar Redis y Celery.

En un despliegue corporativo, PostgreSQL, Redis y la API no deben exponerse directamente a Internet ni a redes de usuarios que no estén autorizadas.

## 5. Despliegue y acceso corporativo

La solución está preparada para operar mediante contenedores Docker, con una configuración de servicios separada y un punto de entrada HTTPS.

Para la instalación institucional se recomienda:

- Servidor autorizado por el área de Tecnología.
- Sistema operativo Linux soportado por la organización.
- Docker Engine y Docker Compose.
- PostgreSQL con almacenamiento persistente.
- Redis y servicios Celery cuando se requieran tareas asíncronas.
- Nginx con certificado TLS válido.
- DNS interno corporativo.
- Reglas de firewall y segmentación de red.
- Gestión segura de secretos.
- Copias de seguridad y procedimientos de recuperación.

### URL institucional

El acceso deberá realizarse mediante un nombre de dominio interno aprobado, por ejemplo:

`https://sicas.interno.empresa`

El nombre anterior es ilustrativo: el dominio definitivo debe ser asignado y configurado por Tecnología.

El acceso debe limitarse a dispositivos y usuarios autorizados dentro de la red corporativa. Si se requiere acceso remoto, deberá utilizarse exclusivamente el mecanismo aprobado por la organización, como una VPN corporativa o una solución de acceso privado.

No se debe publicar la base de datos, Redis ni el puerto interno de la API.

## 6. Procesamiento y análisis de información

La arquitectura del proyecto contempla componentes para la recepción y procesamiento de información, así como para la ejecución de reglas y la preparación de resultados.

Entre las capacidades descritas en el diseño se encuentran:

- Ingesta de información en volumen.
- Procesos de conciliación.
- Ejecución de reglas de negocio.
- Identificación de anomalías.
- Soporte para análisis relacionados con fraude y prevención de legitimación de capitales y financiamiento al terrorismo (LC/FT).
- Procesamiento asíncrono mediante trabajadores.
- Preparación de resultados para revisión y documentación.

La disponibilidad efectiva de cada regla, su cobertura de datos y su precisión deben verificarse mediante pruebas con datos representativos. La detección automatizada constituye apoyo para el análisis y no sustituye el juicio profesional del auditor.

Los cálculos financieros deben utilizar tipos numéricos apropiados para evitar errores de precisión. El uso de `Decimal` se contempla en el diseño del proyecto y debe mantenerse en los cálculos monetarios donde corresponda.

## 7. Organización del código fuente

La estructura funcional documentada del proyecto se organiza en las siguientes áreas. Las rutas exactas deben confirmarse contra el repositorio de la versión V.1.2.

| Ruta o área | Responsabilidad |
|---|---|
| `app/` | Aplicación principal |
| `app/core/` | Servicios compartidos de seguridad, integridad y auditoría |
| `app/modules/` | Módulos funcionales de negocio |
| `app/tasks/` | Tareas asíncronas y programadas |
| `app/static/` | Recursos estáticos e interfaz web, según la estructura de la versión |
| `sql/` | Scripts de creación, actualización y configuración de la base de datos |
| `docs/` | Documentación técnica, funcional y de seguridad |
| `scripts/` | Inicialización, administración y utilidades de mantenimiento |
| `infra/` | Docker, Compose, Nginx y configuración de infraestructura |
| `tests/` | Pruebas unitarias, de integración y de seguridad |

Los módulos de negocio documentados incluyen autenticación, administración, ingesta, motor de auditoría, cumplimiento normativo, informes y analítica. La presencia de un directorio o módulo no implica que todas sus funciones estén completas o habilitadas en el entorno actual.

## 8. Base de datos y evolución del esquema

PostgreSQL almacena la información persistente del sistema. La estructura contempla entidades relacionadas con identidad, permisos, expedientes, auditorías, cédulas, criterios, resultados, evidencias e informes.

Las migraciones SQL permiten organizar la evolución del esquema. Antes de aplicar cambios en un ambiente compartido o productivo se debe:

1. Identificar la versión exacta del código.
2. Verificar el historial de migraciones.
3. Realizar una copia de seguridad.
4. Ensayar la actualización en un ambiente de pruebas.
5. Comprobar las relaciones y restricciones de integridad.
6. Validar los resultados funcionales.
7. Documentar el procedimiento de reversión.

No se recomienda ejecutar migraciones directamente en producción sin revisión, respaldo y autorización.

## 9. Instalación en desarrollo

Consulta primero la guía del proyecto:

[**Guía de inicio — `docs/INICIO.md`](https://github.com/Aalejandro996/SICAS/blob/main/docs/INICIO.md)

Si se trabaja con un entorno Python virtual y las dependencias de desarrollo están definidas en el repositorio, los comandos de referencia son:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
```

Inicialización del entorno de desarrollo:

```bash
python scripts/init_env.py
```

Ejecución de las pruebas unitarias:

```bash
python -m unittest discover -s tests -t . -v
```

Si el proyecto se ejecuta mediante Docker Compose, se debe seguir el archivo Compose y las instrucciones correspondientes a la versión del repositorio. No deben mezclarse comandos de instalación local con procedimientos de contenedores sin verificar las dependencias y variables requeridas.

**Importante:** los comandos anteriores son referencias para desarrollo. Antes de ejecutarlos, confirma que las rutas y dependencias existan en la versión actual. No utilices claves de desarrollo, credenciales de ejemplo ni datos de prueba en producción.

## 10. Pruebas y validación

La validación de SICAS debe cubrir, como mínimo:

- Inicio de sesión, sesiones y recuperación de acceso.
- Asignación de roles y permisos.
- Segregación de funciones y acceso por dominio.
- Creación y consulta de expedientes.
- Creación y ejecución de auditorías.
- Creación de las seis combinaciones de cédulas financieras.
- Sincronización de criterios e ítems.
- Registro y consulta de observaciones y evidencias.
- Ajustes manuales de calificación y su justificación.
- Generación de informes y anexos.
- Ejecución de tareas asíncronas.
- Integridad de los registros de auditoría.
- Restauración de respaldos.
- Acceso HTTPS desde dispositivos autorizados.
- Pruebas de seguridad y aceptación de usuario.

Las pruebas unitarias no sustituyen las pruebas de integración contra PostgreSQL, las pruebas de navegador, las validaciones criptográficas ni las pruebas de aceptación del proceso completo.

## 11. Estado de la versión V.1.2

La versión V.1.2 se encuentra en fase de revisión y validación de sus componentes funcionales y técnicos.

Durante las validaciones del proyecto se registró la creación de cédulas financieras de suscripción y reclamos para Auto, Patrimonial y Personal, con sincronización entre criterios e ítems. También se revisaron la ejecución de los servicios Docker, el acceso HTTPS local y los componentes de API y persistencia.

Estos resultados representan evidencias de pruebas realizadas en el entorno de desarrollo; no constituyen por sí solos una certificación de seguridad ni una aprobación para producción.

Antes de declarar la versión lista para producción, deben completarse y documentarse, según corresponda:

- Validación integral de los módulos financieros y de Sistemas/TI.
- Verificación de roles, permisos y segregación de funciones.
- Pruebas de integración y de extremo a extremo.
- Validación de certificados, secretos y configuración de red.
- Pruebas de carga y rendimiento.
- Verificación de respaldos y recuperación.
- Revisión de informes, anexos, PAC, firmas y documentos institucionales.
- Aprobación de las normas y criterios de auditoría aplicables.
- Aceptación formal de Contraloría, Tecnología y Seguridad de la Información.

## 12. Normativa y criterios de auditoría

Los criterios de las cédulas deben mantener una relación verificable con las políticas internas, procedimientos y disposiciones regulatorias aplicables a la aseguradora.

El marco normativo definitivo debe ser aprobado por Contraloría y las áreas competentes, considerando la jurisdicción aplicable, la regulación venezolana del sector asegurador y los estándares profesionales adoptados por la organización.

Las referencias a estándares de auditoría interna, control interno o seguridad de la información deben documentarse con su edición, alcance y relación con los controles evaluados. No se debe afirmar que SICAS está certificado o que cumple una norma específica sin evidencia formal.

## 13. Documentación relacionada

| Documento o recurso | Propósito |
|---|---|
| `docs/INICIO.md` | Preparación del entorno de desarrollo |
| Documentación de arquitectura | Descripción de componentes y comunicación |
| Documentación de seguridad | Controles de acceso, configuración y protección |
| Documentación de RBAC | Roles, permisos y segregación de funciones |
| Documentación del motor de reglas | Criterios, reglas y procesamiento |
| Documentación de cálculos | Tratamiento de cálculos financieros |
| Documentación de firma | Diseño y validación de firmas electrónicas |
| Checklist de validación | Control de pruebas y requisitos de aceptación |
| `INFORME_PRELIMINAR_SICAS.docx` | Antecedente técnico del proyecto; revisar su versión y vigencia |

La disponibilidad y el contenido de cada archivo deben comprobarse en la versión actual del repositorio.

## 14. Consideraciones de uso

SICAS es una herramienta de apoyo a la función de contraloría y auditoría. Las conclusiones, calificaciones y recomendaciones deben ser revisadas por personal autorizado, de acuerdo con las políticas y responsabilidades institucionales.

La detección automatizada de anomalías no constituye por sí misma una declaración de fraude o incumplimiento. Los hallazgos deben sustentarse en evidencia suficiente, análisis profesional y procedimientos de revisión.

La plataforma debe utilizarse conforme a las políticas corporativas de confidencialidad, protección de datos, conservación de evidencia y control de acceso.

## 15. Licencia y uso institucional

El uso, distribución y modificación de SICAS deben regirse por las condiciones de licencia y propiedad intelectual definidas por los responsables del proyecto y la organización. Si existe una licencia formal en el repositorio, debe consultarse ese archivo antes de redistribuir el código.

---

**SICAS V.1.2**  
*Control, trazabilidad y soporte tecnológico para la auditoría de seguros.*

**Elaborado por:** Adrian Muñoz — Auditor de Sistemas  
**Estado documental:** descripción funcional y técnica sujeta a validación contra la versión vigente del código.
