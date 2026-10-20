# Matriz RBAC

Generada automáticamente desde `app/core/security/permissions.py`.
Leyenda: ● permitido · (vacío) denegado.

## Roles

| Rol | Propósito |
|---|---|
| SYS_ADMIN | Administra plataforma, usuarios, respaldos y salud. Sin acceso a datos de negocio. |
| AUDITOR | Ejecuta cargas, reglas de análisis, gestiona hallazgos y redacta informes. |
| CONTRALOR | Aprueba y firma dictámenes, cierra hallazgos, configura reglas y supervisa el audit trail. |
| GERENCIA | Consulta indicadores ejecutivos e informes aprobados y firmados (solo lectura). |

## Administración y Sistemas

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `user:read` | Ver usuarios | ● |  |  |  |
| `user:create` | Crear usuarios | ● |  |  |  |
| `user:update` | Modificar datos de usuarios | ● |  |  |  |
| `user:deactivate` | Desactivar/reactivar usuarios | ● |  |  |  |
| `user:unlock` | Desbloquear cuentas | ● |  |  |  |
| `user:reset_mfa` | Restablecer factor MFA | ● |  |  |  |
| `role:read` | Ver roles y permisos | ● |  | ● |  |
| `role:assign` | Solicitar asignación/retiro de roles (queda pendiente de aprobación) | ● |  |  |  |
| `role:approve` | Aprobar o rechazar solicitudes de cambio de roles (doble control) |  |  | ● |  |
| `session:revoke` | Revocar sesiones activas de un usuario | ● |  |  |  |
| `param:read` | Ver parámetros del sistema | ● |  | ● |  |
| `param:update` | Modificar parámetros del sistema | ● |  |  |  |
| `backup:read` | Ver estado de respaldos | ● |  |  |  |
| `backup:run` | Ejecutar respaldo manual | ● |  |  |  |
| `backup:restore` | Restaurar respaldo (doble control) | ● |  |  |  |
| `health:read` | Ver salud del servidor y servicios | ● |  |  |  |

## Ingesta de datos

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `ingestion:upload` | Cargar archivos de pólizas/siniestros/reservas |  | ● |  |  |
| `ingestion:read` | Ver estado y resultados de cargas |  | ● | ● |  |
| `ingestion:review_rejects` | Revisar filas rechazadas |  | ● | ● |  |
| `ingestion:cancel` | Cancelar una carga en curso |  | ● |  |  |

## Motor de auditoría

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `rule:read` | Ver reglas y parámetros |  | ● | ● |  |
| `rule:configure` | Modificar umbrales/parámetros de reglas |  |  | ● |  |
| `rule:execute` | Ejecutar el motor de reglas |  | ● | ● |  |
| `finding:read` | Ver hallazgos con detalle |  | ● | ● |  |
| `finding:read_summary` | Ver hallazgos agregados (sin datos personales) |  |  |  | ● |
| `finding:triage` | Cambiar estado/asignar/comentar hallazgos |  | ● | ● |  |
| `finding:escalate` | Escalar hallazgo a Contraloría |  | ● |  |  |
| `finding:close` | Cerrar hallazgo (falso positivo / resuelto) |  |  | ● |  |

## Informes y firma

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `report:draft` | Redactar providencias y dictámenes (borrador) |  | ● |  |  |
| `report:read` | Ver borradores y en revisión |  | ● | ● |  |
| `report:read_approved` | Ver informes aprobados y firmados |  | ● | ● | ● |
| `report:submit` | Enviar borrador a aprobación |  | ● |  |  |
| `report:approve` | Aprobar o devolver informe |  |  | ● |  |
| `report:sign` | Firmar y sellar informe (requiere MFA reciente) |  |  | ● |  |
| `report:verify_signature` | Verificar firma/integridad de un PDF |  | ● | ● | ● |
| `report:export` | Exportar informes (PDF/Excel) |  | ● | ● |  |
| `template:manage` | Gestionar plantillas de informes |  |  | ● |  |

## Cumplimiento LC/FT y regulatorio

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `lcft:alert_read` | Ver alertas LC/FT |  | ● | ● |  |
| `lcft:alert_manage` | Analizar y gestionar alertas LC/FT |  | ● | ● |  |
| `lcft:rule_configure` | Configurar reglas/umbrales LC/FT |  |  | ● |  |
| `regulatory:read` | Ver reportes regulatorios |  | ● | ● |  |
| `regulatory:generate` | Generar reportes regulatorios |  | ● |  |  |
| `regulatory:approve` | Aprobar reporte regulatorio para envío |  |  | ● |  |

## Analítica

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `dashboard:operational` | Ver dashboards operativos de auditoría |  | ● | ● |  |
| `dashboard:executive` | Ver dashboards ejecutivos/KPIs |  |  | ● | ● |
| `dashboard:contralor` | Acceso exclusivo al dashboard agregado de Contraloría |  |  | ● |  |
| `kpi:manage` | Crear, modificar y desactivar KPI del dashboard de Contraloría |  |  | ● |  |
| `kpi:export` | Exportar KPIs |  |  | ● |  |

## Auditorías (expedientes, cédulas, informes)

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `audit:read` | Ver expedientes, auditorías, cédulas y observaciones |  | ● | ● |  |
| `audit:read_final` | Ver informes finales aprobados y firmados |  | ● | ● | ● |
| `audit:manage` | Crear expedientes y auditorías; trabajar cédulas, observaciones y evidencias |  | ● |  |  |
| `audit:rate` | Ajustar manualmente la calificación (a criterio del Auditor) |  | ● |  |  |
| `audit:template_manage` | Editar los criterios de las cédulas (plantillas) |  |  | ● |  |
| `audit:unit_manage` | Administrar el catálogo de unidades y sucursales |  |  | ● |  |
| `audit:report_draft` | Generar informes previos y finales (automático) |  | ● |  |  |
| `audit:report_submit` | Enviar el informe final al Contralor / el previo a la unidad |  | ● |  |  |
| `audit:report_approve` | Aprobar o devolver el informe final (Contralor) |  |  | ● |  |
| `audit:report_approve_jefe` | Aprobar o devolver el informe final como Jefe de Auditoría |  |  |  |  |
| `audit:report_approve_gerente` | Aprobar y devolver el informe final como Gerencia |  |  |  | ● |
| `audit:initial` | Estampar las iniciales del auditor en el informe |  | ● |  |  |
| `audit:sign_contralor` | Firma electrónica del Contralor en el informe final |  |  | ● |  |
| `audit:sign_gerente` | Firma electrónica del Gerente de Control Interno |  |  |  | ● |
| `audit:pac_send` | Enviar el PAC (anexo en Excel) a la unidad |  | ● |  |  |
| `audit:general_read` | Acceso a auditorías generales existentes |  | ● |  |  |
| `audit:financial_read` | Acceso exclusivo a auditorías financieras |  |  |  |  |
| `audit:financial_manage` | Crear y trabajar auditorías financieras |  |  |  |  |
| `audit:financial_execute` | Pantalla operativa del Auditor Financiero |  |  |  |  |
| `audit:financial_review` | Supervisar auditorías e informes financieros |  |  |  |  |
| `audit:systems_read` | Acceso exclusivo a auditorías de sistemas/TI |  |  |  |  |
| `audit:systems_manage` | Crear y trabajar auditorías de sistemas/TI |  |  |  |  |
| `audit:systems_execute` | Pantalla operativa del Auditor de Sistemas |  |  |  |  |
| `audit:systems_review` | Supervisar auditorías e informes de sistemas/TI |  |  |  |  |

## Audit trail

| Permiso | Descripción | SYS_ADMIN | AUDITOR | CONTRALOR | GERENCIA |
|---|---|---|---|---|---|
| `auditlog:read` | Consultar el audit trail |  |  | ● |  |
| `auditlog:verify_chain` | Verificar integridad de la cadena de hashes | ● |  | ● |  |
| `auditlog:export` | Exportar el audit trail |  |  | ● |  |

## Segregación de funciones (SoD)

Ningún usuario puede acumular ambos permisos de un par. El servicio de asignación de roles rechaza la combinación y registra el intento en el audit trail.

| Permiso A | Permiso B | Motivo |
|---|---|---|
| `report:draft` | `report:approve` | Quien redacta no aprueba. |
| `report:draft` | `report:sign` | Quien redacta no firma. |
| `ingestion:upload` | `finding:close` | Quien carga datos no cierra hallazgos. |
| `user:create` | `auditlog:read` | Quien administra usuarios no consulta el audit trail. |
| `backup:restore` | `report:sign` | Quien restaura datos no firma informes. |
| `param:update` | `rule:configure` | Parámetros de plataforma y reglas de auditoría separados. |
| `role:assign` | `report:approve` | Quien asigna roles no aprueba informes. |
| `role:assign` | `role:approve` | Quien solicita un cambio de roles no lo aprueba. |
| `user:create` | `role:approve` | Quien crea usuarios no aprueba sus roles. |
| `audit:manage` | `audit:report_approve` | Quien ejecuta la auditoría no aprueba su informe. |
| `audit:report_draft` | `audit:sign_contralor` | Quien genera el informe no lo firma como Contralor. |
| `audit:report_draft` | `audit:sign_gerente` | Quien genera el informe no lo firma como Gerente de Control Interno. |
| `audit:sign_contralor` | `audit:sign_gerente` | Las dos firmas finales las ponen personas distintas. |

## Reglas adicionales (no expresables solo con permisos)

- **Doble control:** el aprobador de un informe debe ser distinto de su redactor (`approved_by <> drafted_by`).
- **Firma:** exige MFA reciente (step-up, máx. 5 min) además del permiso `report:sign`.
- **Combinación de roles:** `find_sod_violations()` se ejecuta al asignar roles.
- **Restauración de respaldos y cambio de roles:** requieren segunda aprobación de otro usuario con permiso equivalente.
- **GERENCIA** nunca ve datos personales de asegurados: solo agregados e informes aprobados.
