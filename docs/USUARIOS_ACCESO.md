# Gestión de usuarios y acceso

## Ciclo de vida de una cuenta

1. **Alta** (SYS_ADMIN, `user:create`, MFA reciente): se crea el usuario **sin roles**, con contraseña temporal aleatoria que se muestra una sola vez.
2. **Primer ingreso**: cambio obligatorio de contraseña y alta de MFA.
3. **Roles** (doble control): el SYS_ADMIN *solicita* (`role:assign`) con un motivo de al menos 10 caracteres; **otra persona** con `role:approve` (CONTRALOR) lo aprueba o rechaza. No pueden resolver la solicitud ni el solicitante ni la persona afectada. Al aprobar se revalida la segregación de funciones con el estado actual y se **revocan las sesiones** del usuario.
4. **Operación**: bloqueo automático, desbloqueo por SYS_ADMIN, reset de MFA (con revocación de sesiones).
5. **Desactivación**: temporal y reversible; revoca sesiones. El historial queda en el audit trail.
6. **Baja definitiva** (doble control): el SYS_ADMIN la *solicita* (`user:deactivate`, MFA reciente) con una justificación de al menos 15 caracteres; el CONTRALOR (`role:approve`) la aprueba o rechaza. Es lógica, nunca un borrado: la cuenta queda desactivada, sin roles ni sesiones y fuera de las listas, porque la bitácora y las firmas la referencian. No puede reactivarse ni dejar el sistema sin un SYS_ADMIN activo.

## Suplencias temporales del flujo del informe final

Cuando falta el titular de una etapa (Jefe de Auditoría, Gerencia o Contralor), otra persona actúa en su nombre por un máximo de **90 días** con un motivo registrado. El flujo Auditor → Jefe → Gerente → Contralor **no cambia**.

- **Quién autoriza**: las suplencias de Jefe y de Gerencia, el Contralor (`audit:report_approve`); la del Contralor, Gerencia (`audit:report_approve_gerente`). Nadie se autoriza a sí mismo. La revocan quien la autoriza o el propio titular.
- **Qué recibe el suplente**: solo los permisos de esa etapa, mientras la suplencia está vigente. Si la combinación con sus roles viola la segregación de funciones, la suplencia no se crea ni se aplica. Por ejemplo, quien ejecuta auditorías no cubre al Contralor ni a Gerencia, y el suplente del Jefe debe pertenecer al mismo dominio. El Administrador del Sistema no puede ser suplente.
- **Trazabilidad**: cada decisión del suplente queda en `report_transitions` con la suplencia (`delegation_id`) y el titular (`on_behalf_of`). Se muestra como «en nombre de» en el historial y en el PDF.
- **Firma**: el suplente de Gerencia o del Contralor firma con **su propio certificado** (.p12/.pfx). Lo sube desde «Suplencias › Mi certificado» y se guarda cifrado con AES-256-GCM (`SICAS_KEYS`).

## Reglas de los motores (doble control)

El SYS_ADMIN propone (`rule:propose`) reglas nuevas o cambios para los motores SUDEASEG, de Sistemas y analítico. Cada propuesta lleva un motivo de al menos 10 caracteres. El CONTRALOR las aprueba (`rule:configure`). Quien propone no aprueba (`SOD_CONFLICTS` y `CHECK` en la base de datos). Al aprobar se vuelve a validar el cambio y se rechaza si la regla cambió después de la propuesta. Las reglas del motor analítico están en el código: desde la aplicación solo se ajustan sus parámetros y se activan o desactivan.

## Reglas que el sistema impone

| Regla | Dónde se aplica |
|---|---|
| Nadie solicita ni aprueba cambios para sí mismo | Servicio **y** restricciones `CHECK` en la base de datos |
| El solicitante no puede aprobar | Servicio y base de datos |
| Combinaciones de roles con conflicto (9 pares) se rechazan al solicitar **y** al aprobar | `permissions.SOD_CONFLICTS` |
| No se puede desactivar ni retirar el rol al **último** SYS_ADMIN activo | Servicio |
| Un usuario no puede desactivarse ni resetearse el MFA a sí mismo | Servicio |
| Los permisos viajan en el token; cualquier cambio de rol revoca las sesiones | Servicio |

## Combinaciones de roles prohibidas (SoD)

Redactor + aprobador/firmante de informes · cargar datos + cerrar hallazgos · administrar usuarios + leer el audit trail · restaurar respaldos + firmar · parámetros del sistema + reglas de auditoría · solicitar roles + aprobar roles / aprobar informes · crear usuarios + aprobar roles. Ver la matriz completa en `RBAC_MATRIX.md`.

## Endpoints

| Método y ruta | Permiso | MFA reciente |
|---|---|---|
| `GET /admin/users` | `user:read` | — |
| `POST /admin/users` | `user:create` | Sí |
| `POST /admin/users/<id>/deactivate` · `/activate` | `user:deactivate` | Sí |
| `POST /admin/users/<id>/unlock` | `user:unlock` | — |
| `POST /admin/users/<id>/reset-mfa` | `user:reset_mfa` | Sí |
| `POST /admin/role-requests` | `role:assign` | — |
| `GET /admin/role-requests` | `role:read`/`role:approve`/`role:assign` | — |
| `POST /admin/role-requests/<id>/decision` | `role:approve` | Sí |
| `POST /admin/users/<id>/removal-request` | `user:deactivate` | Sí |
| `GET /admin/removal-requests` | `user:read`/`role:approve` | — |
| `POST /admin/removal-requests/<id>/decision` | `role:approve` | Sí |
| `GET /rules-admin/catalogs` · `/requests` | `rule:propose`/`rule:configure` | — |
| `POST /rules-admin/requests` | `rule:propose` | Sí |
| `POST /rules-admin/requests/<id>/decision` | `rule:configure` | Sí |
| `GET /audits/delegations` | lectura de auditorías | — |
| `POST /audits/delegations` · `GET /audits/delegations/candidates` | `audit:report_approve`/`audit:report_approve_gerente` | Sí (alta) |
| `POST /audits/delegations/<id>/revoke` | quien autoriza o el titular | Sí |
| `POST /audits/signing-certificate` | suplente de Gerencia o del Contralor | Sí |

Todo queda en el audit trail: `USER_CREATED`, `USER_REMOVAL_REQUESTED`, `USER_REMOVED`, `RULE_CHANGE_REQUESTED/APPROVED/REJECTED`, `DELEGATION_CREATED/REVOKED`, `SIGNING_CERTIFICATE_UPLOADED`, `ROLE_CHANGE_REQUESTED/APPROVED/REJECTED`, `ROLE_DECISION_REJECTED`, `USER_DEACTIVATED`, `USER_MFA_RESET`, `LOGIN_OK/FAILED/REJECTED`, `MFA_FAILED`, etc.

## Primer arranque

`scripts/bootstrap_admin.py` crea el primer SYS_ADMIN y el primer CONTRALOR (personas distintas). Funciona solo mientras el rol no tenga usuarios activos y deja el evento `BOOTSTRAP_USER_CREATED`. Después de eso, todo cambio de rol pasa por doble control.

## Herramientas del Administrador del Sistema (doble verificación)

Toda acción del Administrador en estas herramientas pide **MFA reciente** al solicitarla y se ejecuta solo cuando el **Contralor la aprueba**, también con MFA reciente. Quien solicita no puede aprobar (`SOD_CONFLICTS` y `CHECK` en la base de datos). Las consultas (monitor, certificados, listados) no cambian nada y no pasan por aprobación.

| Herramienta | Qué hace | Pantalla |
|---|---|---|
| Anulación de auditorías | Anula una auditoría en curso y sin informes: queda `ANULADA`, fuera de las listas y con el código liberado; la bitácora la conserva | Anulación de auditorías / Solicitudes |
| Monitor | Estado del worker y del beat (latido cada minuto), respaldos, cargas fallidas o detenidas; avisa a los administradores | Monitoreo |
| Certificados y firmas | Vencimiento de certificados personales e institucionales (aviso 30 días antes) y firmantes sin firma escaneada | Monitoreo |
| Política de seguridad | Intentos antes del bloqueo, minutos de bloqueo, vigencia del MFA reciente, duración de la sesión y vencimiento de contraseñas | Monitoreo |
| Revisión de accesos | Roles, último ingreso, cuentas sin uso, sin MFA o con conflicto SoD; exporta CSV, propone desactivaciones y guarda la revisión como evidencia | Revisión de accesos |
| Sesiones activas | Lista quién está conectado y cierra sus sesiones | Revisión de accesos |
| Catálogos | Unidades y sucursales y codificación institucional, con el mismo circuito que las reglas de los motores | Reglas de los motores |
| Verificación de restauración | Comprueba que el respaldo existe, que su SHA-256 coincide y que `pg_restore` lo lee completo. No sobrescribe producción | Monitoreo |
| Prueba de correo | Envía un correo de prueba con la configuración SMTP vigente | Monitoreo |
