# SICAS — Inspección técnica (Etapa A)
## Evolución del módulo de Auditoría de Sistemas

**Fecha:** 2026-10-25 · **Base inspeccionada:** `main` @ `a33e48d` · **Alcance:** solo lectura (sin migraciones, sin cambios de datos, sin despliegues)

---

## 0. Resumen ejecutivo

SICAS ya implementa **la mayor parte del esqueleto** que pide la especificación: flujo Auditor → Jefe → Gerencia → Contraloría con estados en BD, aprobaciones atadas al SHA-256 del contenido, RBAC verificado en servidor, bitácora encadenada e inmutable, y (desde `7337ce8`) instantáneas de puntuación por fase.

Lo que falta es **trazabilidad de grano fino y versionado**: hoy varias operaciones sobrescriben datos (`UPDATE`) y la historia queda solo en `audit.audit_log`, que se escribe en una transacción separada y "best effort". La mejora debe centrarse en eso, no en rehacer el flujo.

| # | Requisito de la especificación | Estado actual | Brecha |
|---|---|---|---|
| 1 | Cuadro referencia vs. resultado | Parcial | Fórmula y umbrales existen; "nota esperada" no está definida en ningún lugar |
| 2 | Edición controlada de segmentos | Parcial | Solo el equipo auditor edita; los revisores solo comentan/devuelven |
| 3 | Edición y seguimiento de observaciones | Parcial | `UPDATE` en sitio; sin motivo, sin versión original, sin estado pendiente/atendida |
| 4 | Bitácora con usuario | Existe | No es atómica con el cambio; no se puede consultar por expediente de forma directa |
| 5 | Historial de calificaciones por fase | Existe (nuevo) | Falta evidencia, versión de regla, motivo y variación respecto del previo |
| 6 | Revisión / devolución / aprobación | Existe | Sin tabla de transiciones; devolución sin destino ni puntos; sin control de concurrencia |
| 7 | Resultados y trazabilidad en informe final | No | El informe no incluye historial, devoluciones ni aprobaciones |

---

## 1. Inventario

### 1.1 Stack y despliegue
- Flask + PostgreSQL 16 + Celery/Redis, SQL crudo con `sqlalchemy.text` (sin ORM), migraciones como scripts `sql/NNN_*.sql` aplicados por `scripts/migrate.py`.
- **Render:** `sicas-api`, `sicas-worker`, `sicas-beat`, `sicas-kv`, `sicas-db` (virginia). `sicas-api` está *live* en `a33e48d` (= HEAD), auto-deploy apagado y `preDeployCommand: python scripts/migrate.py`. La BD tiene allowlist vacío (no acepta conexiones externas): no pude verificar si la 024 quedó aplicada en producción.
- **Docker local** (`infra/docker`): api, db, worker, beat, nginx, redis arriba. La imagen `docker-api` es del **2026-10-21**, anterior a los 6 últimos commits; la BD local **no tiene** `engagement.phase_score_snapshots` (migración 024 sin aplicar). Hay 1 auditoría (SISTEMAS) y 0 informes.

### 1.2 Modelo de datos relevante (`schema engagement`)
| Tabla | Uso | Mutabilidad |
|---|---|---|
| `audits` | Fase (`PLANIFICACION/TRABAJO_CAMPO/INFORME`), estado, nota manual | UPDATE |
| `phase_log` | Cambios de fase con nota | Solo INSERT por grant (sin trigger) |
| `worksheets`, `items` | Cédulas, respuestas (`results` JSONB), nota auto/manual | UPDATE |
| `observations` | Hallazgos + respuesta de la unidad + PAC | UPDATE en sitio |
| `evidence` | Archivos con SHA-256 | Append-only (trigger) |
| `reports` | Previo/final, `body` JSONB + `body_sha256`, aprobaciones Jefe/Gerente/Contralor | UPDATE (incluido el `body`) |
| `report_comments` | REVISION / RESPUESTA / DEVOLUCION | Append-only |
| `signoffs`, `signed_documents` | Iniciales y firmas PAdES | Append-only |
| `phase_score_snapshots` (024) | Instantánea de puntuación | Append-only |
| `audit.audit_log` | Bitácora global, hash encadenado, particionada | Append-only, INSERT-only grant |

### 1.3 Endpoints (`app/modules/engagement/api.py`)
- Fase: `POST /<aid>/phase` (avanza/retrocede de a una; retroceso exige motivo; genera snapshot).
- Calificación: `PUT /<aid>/rating`, `/items/<iid>/rating`, `/worksheets/<wid>/rating` (manual 0–100 con justificación ≥10 caracteres).
- Ítems/observaciones: `PUT /items/<iid>`, `POST /<aid>/observations`, `PUT /observations/<oid>`.
- Informe: crear, regenerar, iniciales, `submit`, `return`, `approve/jefe`, `sign/gerente`, `sign/contralor`, PDF, PAC.
- La guarda común `load(write=True)` exige: ser del equipo, auditoría `IN_PROGRESS`, fase válida y que **ningún informe final esté en `IN_REVIEW/APPROVED/SIGNED`**.

### 1.4 Flujo de estados vigente (`workflow.py`)
```
DRAFT/RETURNED ──submit──▶ IN_REVIEW ──Jefe aprueba──▶ GERENCIA ──Gerente aprueba+firma──▶ CONTRALOR ──Contralor aprueba+firma──▶ SIGNED
        ▲                      │                         │                                    │
        └──────────────────────┴──────── return (cualquier etapa, ≥10 caracteres) ─────────────┘
```
Corresponde casi 1:1 con la sección 7 de la especificación (En preparación = DRAFT, Devuelto = RETURNED, Aprobado definitivamente = SIGNED). `APPROVED` y `SENT` quedan como estados heredados.

### 1.5 RBAC
Fuente real: `app/core/security/permissions.py`. Roles disponibles para el alcance: `AUDITOR_SISTEMAS`, `JEFE_AUDITORIA_SISTEMAS` (`audit:report_approve_jefe`, `audit:systems_review`), `GERENCIA` (`audit:report_approve_gerente`, `audit:sign_gerente`), `CONTRALOR` (`audit:report_approve`, `audit:sign_contralor`, `auditlog:read`). Hay SoD, step-up MFA para aprobar/firmar y validaciones de que el revisor no es del equipo ni aprobador previo.

**Conclusión:** para el flujo no hacen falta permisos nuevos. Solo harían falta si se decide que los revisores **editen** (ver D3) o que el equipo consulte la bitácora de su expediente.

### 1.6 Puntuación (`scoring.py`)
- Sistemas: `Existencia 40 % + Documento 30 % + Evidencia 30 %` por control, promedio ponderado por `weight`.
- Niveles: `>90` Excelente · `70–90` Satisfactorio · `60–69.99` Aceptable · `50–59.99` Necesita mejoras · `<50` No satisfactoria. Umbrales sobreescribibles vía `repo.thresholds()`.
- Nota de cédula = promedio de ítems; nota de auditoría = promedio de cédulas; nota manual sustituye a la automática y la automática se conserva.

### 1.7 Pruebas
Ejecutadas en un contenedor temporal desde la imagen `docker-api`: **198 pasan, 2 omitidas, 1 falla** (`test_auth_qr`: falta `qrcode` en la imagen desactualizada; no es un fallo de código). `pytest` no figura en `requirements/dev.txt` y el `.venv` local está roto (apunta a un Python 3.14 que ya no existe). Hay solo 4 pruebas de autorización de informes y 2 de snapshots; no hay pruebas de API para saltos de etapa.

---

## 2. Hallazgos

### 2.1 Seguridad: requiere acción inmediata
- **S1 — Secretos versionados.** `Orden de prioridades.md` está en git desde `41b20c8` (2026-10-15) y contiene lo que parecen claves en base64 y una contraseña en claro. Si el repo `Aalejandro996/SICAS` es público o se comparte, hay que **rotarlas** y sacar el archivo del historial. Los valores no se reproducen en este informe.

### 2.2 Integridad y trazabilidad (afectan directamente a la especificación)
- **T1 — Bitácora no atómica.** `audit()` hace su propio `commit` *después* del commit de negocio y traga errores. Si falla, el cambio queda hecho sin registro. Esto contradice §5 ("registro que permita reconstruir los cambios").
- **T2 — Sin consulta por expediente.** Los eventos usan `entity_id` = ítem, observación o informe, y no llevan `audit_id`. Reconstruir un expediente obliga a cruzar IDs.
- **T3 — El cuerpo del informe se sobrescribe.** `regenerate` hace `UPDATE reports SET body=…`. El contenido que vio el Jefe antes de devolverlo se pierde y queda solo su hash. Contradice §9 ("no debe reconstruirse a partir de datos que hayan cambiado").
- **T4 — La devolución borra aprobaciones.** `return_report` pone en `NULL` las columnas `jefe_/gerente_/contralor_approved_*`. La historia de quién aprobó queda solo en `audit_log` (ver T1).
- **T5 — Transiciones sin control de concurrencia.** `set_report_status` hace `UPDATE … WHERE id=:i` sin comprobar el estado de origen. Dos peticiones simultáneas pueden pasar ambas la validación. Además, en la devolución el comentario y el cambio de estado van en commits distintos.
- **T6 — Observaciones sin historia propia.** No existen motivo, versión original ni estado pendiente/atendida.

### 2.3 Funcionales
- **F1 — Ambigüedad en la fórmula de Sistemas.** `update_item` acepta `control = PARCIAL` y `system_statistics` lo cuenta como respondido, pero `system_item_score` lo **ignora** (no puntúa). Un control "parcial" no afecta la nota. Hay que confirmar la regla antes de construir el cuadro comparativo.
- **F2 — "Nota esperada" inexistente.** No hay configuración de una nota de referencia por cédula o auditoría. Solo existen los umbrales de nivel.
- **F3 — Snapshot incompleto frente a §2.1/§6.** Guarda ítems, respuestas, notas y umbrales. **No** guarda la evidencia vinculada, la versión de plantilla o regla, el motivo (solo enlazable vía `phase_log_id`) ni la variación respecto del anterior. Se etiqueta con la fase que se **cierra**, lo cual es correcto, pero conviene explicitarlo.
- **F4 — No hay re-emisión tras `SIGNED`.** Con un final firmado, `load(write=True)` bloquea todo, incluso crear una nueva versión. Tampoco puede actualizarse el `pac_status` de las observaciones después de la firma, lo que conviene confirmar.
- **F5 — Visibilidad en etapa CONTRALOR.** `get_rep` deja ver el informe en estado `CONTRALOR` a cualquiera con `audit:read_final` del mismo dominio (auditores ajenos al equipo), aunque el permiso se describe como "aprobados y firmados". Hay que confirmar si es intencional.

### 2.4 Higiene
- `app/modules/engagement/permissions.py` es una **copia obsoleta y divergente** del RBAC real: sin `dashboard:contralor` ni `kpi:manage`, y con otros permisos para GERENCIA y los Jefes. No se importa en ningún sitio. Conviene eliminarla.
- Dos migraciones con prefijo `010_`: funciona por orden alfabético, pero es frágil.
- `render.yaml` declara `maintenanceMode.enabled: true` y el servicio real lo tiene en `false` (deriva entre blueprint y realidad).
- Imagen Docker local desactualizada; `pytest` ausente de `requirements/dev.txt`; varios `.bak` sin versionar en `app/static` (no se sirven en producción, verificado con 404).

---

## 3. Propuesta de diseño mínimo (Etapa B, para validar)

Todo es aditivo. No se toca el dashboard del Contralor, el motor de analítica ni las tablas financieras.

1. **`engagement.report_transitions`** (append-only): `report_id, report_version, body_revision, from_status, to_status, actor_id, actor_role, comment, body_sha256, return_target, created_at`. Se inserta en la **misma transacción** que el cambio de estado. Resuelve T4 y parte de §7.
2. **`engagement.report_body_revisions`** (append-only): cada generación o regeneración guarda `body` + `sha256` + `revision`. `reports.body` pasa a ser "la revisión vigente". Resuelve T3 y §9.
3. **Compare-and-set** en `set_report_status(rid, expected_status, new_status, …)` con `WHERE status = :expected` y verificación de filas afectadas, más comentario y estado en un solo commit. Resuelve T5.
4. **`engagement.change_events`** (append-only, por expediente): `audit_id, report_id, entity_type, entity_id, field, old, new, reason, actor_id, actor_role, workflow_stage, created_at`, escrita en la misma transacción que el cambio. `audit.audit_log` se mantiene como bitácora de seguridad. Resuelve T1, T2 y §5.
5. **Observaciones:** `observation_revisions` (append-only, con motivo obligatorio en etapa de revisión) y `review_points` (punto de devolución → observación o ítem, estado `PENDIENTE/ATENDIDO`, quién lo atendió). Resuelve T6 y §4.
6. **Snapshot v2:** añadir al `scorecard` la evidencia (id, sha, ítem), la versión de plantilla, el motivo y `rule_version`. La variación respecto del previo se calcula al leer, sin almacenarla.
7. **Informe final:** nuevas secciones en `assemble`/`report_builder`: historial por fase, variaciones con motivos, resumen de devoluciones y aprobaciones, e identificación de la revisión aprobada.

Orden sugerido de incrementos: **3 → 1 → 2 → 4 → 5 → 6 → 7**, cada uno con sus pruebas de API negativas (saltos de etapa, actor no autorizado, dominio cruzado).

---

## 4. Decisiones pendientes (bloquean la codificación de reglas, no el diseño)

- **D1:** ¿Cómo puntúa `control = PARCIAL` en Sistemas? (hoy no puntúa; ver F1)
- **D2:** ¿Qué es la "nota esperada" del cuadro comparativo? ¿El umbral de Satisfactorio (70)? ¿Un valor configurable por cédula?
- **D3:** En revisión, ¿Jefe, Gerencia y Contraloría **editan directamente** observaciones y segmentos, o solo devuelven con puntos y el auditor corrige? (lo primero requiere permisos nuevos y ampliar `load()`)
- **D4:** Destino de cada devolución: ¿siempre al equipo auditor, o Contraloría puede devolver a Gerencia o al Jefe?
- **D5:** Tras `SIGNED`: ¿nueva versión del informe (v2), con qué aprobaciones y quién la autoriza?
- **D6:** Correspondencia exacta entre las fases del Jefe de Auditoría y `PLANIFICACION/TRABAJO_CAMPO/INFORME`.
- **D7:** ¿Es intencional que auditores no miembros vean el informe en etapa CONTRALOR? (F5)
- **D8:** ¿Se puede seguir actualizando el seguimiento del PAC después de la firma? (F4)
