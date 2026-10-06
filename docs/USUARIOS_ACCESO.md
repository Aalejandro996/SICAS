# Gestión de usuarios y acceso

## Ciclo de vida de una cuenta

1. **Alta** (SYS_ADMIN, `user:create`, MFA reciente): se crea el usuario **sin roles**, con contraseña temporal aleatoria que se muestra una sola vez.
2. **Primer ingreso**: cambio obligatorio de contraseña y alta de MFA.
3. **Roles** (doble control): el SYS_ADMIN *solicita* (`role:assign`) con un motivo de al menos 10 caracteres; **otra persona** con `role:approve` (CONTRALOR) lo aprueba o rechaza. No pueden resolver la solicitud ni el solicitante ni la persona afectada. Al aprobar se revalida la segregación de funciones con el estado actual y se **revocan las sesiones** del usuario.
4. **Operación**: bloqueo automático, desbloqueo por SYS_ADMIN, reset de MFA (con revocación de sesiones).
5. **Baja**: desactivación (nunca borrado); revoca sesiones. El historial queda en el audit trail.

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

Todo queda en el audit trail: `USER_CREATED`, `ROLE_CHANGE_REQUESTED/APPROVED/REJECTED`, `ROLE_DECISION_REJECTED`, `USER_DEACTIVATED`, `USER_MFA_RESET`, `LOGIN_OK/FAILED/REJECTED`, `MFA_FAILED`, etc.

## Primer arranque

`scripts/bootstrap_admin.py` crea el primer SYS_ADMIN y el primer CONTRALOR (personas distintas). Funciona solo mientras el rol no tenga usuarios activos y deja el evento `BOOTSTRAP_USER_CREATED`. Después de eso, todo cambio de rol pasa por doble control.
