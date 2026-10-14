# Dashboard del Contralor — primera fase

## Seguridad y alcance

- Página frontend: `contralor-dashboard`, visible mediante el permiso `dashboard:contralor`.
- Lecturas y exportación protegidas en el servidor; el dashboard no crea ni modifica auditorías, informes, cédulas u observaciones.
- Crear, editar y desactivar KPI requiere además `kpi:manage`, concedido únicamente al rol `CONTRALOR`. Las metas y umbrales deben ser no negativos; los valores porcentuales no pueden exceder 100.
- Exportar requiere ambos `dashboard:contralor` y `kpi:export`; que otro rol tenga el permiso histórico `kpi:export` no le concede acceso a este módulo.
- Las métricas KPI se eligen de un catálogo cerrado. No se ejecutan expresiones SQL ingresadas por el usuario.

## Métricas iniciales

`AUDITS_TOTAL`, `AUDITS_IN_PROGRESS`, `AUDITS_CLOSED`, `AUDIT_COMPLETION_PCT`, `OBSERVATIONS_TOTAL`, `HIGH_RISK_OBSERVATIONS`, `HIGH_RISK_SHARE_PCT`, `AVG_CLOSED_AUDIT_DAYS`, `AVG_PHASE_HOURS`, `INGESTION_AVG_SECONDS`, `INGESTION_REJECTION_PCT`.

## Definiciones y cautelas

- La serie de auditorías se filtra por `engagement.audits.created_at`. Para las auditorías creadas dentro del rango, `cerradas` representa su estado actual; no indica el número de cierres que ocurrieron en ese mismo rango, porque `engagement.audits` no tiene una fecha de cierre explícita fiable.
- Las brechas se filtran por su propia `engagement.observations.created_at` y se atribuyen a la unidad, dominio y equipo de la auditoría relacionada, aunque esa auditoría haya comenzado antes del rango. El histórico mezcla ambos hechos con leyendas explícitas: auditorías por apertura y brechas por fecha de creación.
- La duración de una auditoría cerrada usa la fecha de creación y la última transición registrada en `engagement.phase_log`. Si no hay transiciones registradas, la duración de cierre queda sin dato en vez de inventar cero; no debe interpretarse como un tiempo de trabajo real.
- La duración por fase es tiempo calendario transcurrido entre transiciones registradas; la fase vigente se mide hasta el momento de consulta. No mide uso activo del teclado ni horas efectivamente trabajadas.
- El histórico rellena con cero los períodos intermedios sin registros para no deformar las tendencias. Los informes Excel incluyen comparativo por unidad, matriz de riesgo por unidad y comparativo por auditor. Los textos externos al libro se neutralizan para evitar que se interpreten como fórmulas.
- La medición de cargas usa `insurance.ingestion_jobs.created_at`, `finished_at`, `rows_processed` y `rows_rejected`; la duración incluye espera en cola si existe y no es equivalente al tiempo efectivo de cómputo o trabajo humano.
- La tabla `insurance.ingestion_jobs` no tiene relación con unidad en el esquema actual. Por ello los indicadores de cargas se presentan como globales; el filtro de auditor puede limitar por `uploaded_by`.
- `observations` se atribuyen a la auditoría relacionada; los agregados respetan filtros por fecha de creación de la observación, unidad, dominio y auditor asignado. La tabla y hoja de riesgos por unidad desglosan crítico, alto, medio, bajo, sin clasificar y otros valores no estándar.
- Los KPI de auditorías evalúan la cohorte creada en el período; los KPI de observaciones evalúan observaciones creadas en el período. Los KPI evalúan un período parcial hasta la fecha actual y pueden mostrar `SIN_DATOS` cuando el denominador sea cero o no haya observaciones.
- La primera fase no intenta inferir trabajo activo individual. Una fase posterior debe añadir eventos de actividad explícitos (inicio/pausa/reanudación/fin) y probar su integridad antes de publicar ese indicador.

## Rutas

- `GET /api/v1/analytics/contralor/options`
- `GET /api/v1/analytics/contralor/overview`
- `GET /api/v1/analytics/contralor/kpis`
- `POST /api/v1/analytics/contralor/kpis`
- `PATCH /api/v1/analytics/contralor/kpis/<uuid>`
- `GET /api/v1/analytics/contralor/export.xlsx`

## Migración

`sql/014_contralor_dashboard_kpis.sql` es aditiva y debe revisarse y respaldarse. El instalador de fase 1 no ejecuta migraciones, no conecta con la base de datos para cambios, no reinicia servicios y no despliega imágenes.

## Comparación por dominio y criterios de interpretación

El panel comparativo FINANCIERA/SISTEMAS aparece en paralelo y conserva ambos dominios visibles aunque se utilice el selector de dominio en el resto del dashboard. Respeta el período, unidad y auditor seleccionados. Las auditorías e ítems se agrupan por fecha de creación de la auditoría; las observaciones formales se agrupan por la fecha propia de creación de la observación. Por esa razón, los totales no deben sumarse como si fueran una misma cohorte temporal.

Las observaciones formales sin `item_id` se muestran por separado de los criterios vinculados. Una observación general es admitida por el modelo actual; no debe considerarse un error ni eliminarse automáticamente. La validación de creación debe impedir que un ítem de otra auditoría se asocie por error.

Para auditorías con estado de cierre, la duración hasta cierre se calcula desde `created_at` hasta `pac_sent_at`, que es el evento que en el flujo actual cambia el estado a `CLOSED`. La última fase de una auditoría cerrada termina en ese mismo instante. Si falta `pac_sent_at`, el sistema deja la duración sin dato en lugar de inferir un cierre a partir del último cambio de fase. Las horas por fase siguen siendo tiempo calendario transcurrido; no equivalen a tiempo activo del auditor.

La creación y edición de KPI registra un evento en `audit.audit_log` después de confirmar la transacción de negocio. Este evento es complementario a los campos de creador y actualizador almacenados en la definición del KPI.


## Extensión completa: alertas, flujo, calidad, carga y cortes históricos

La segunda extensión agrega al dashboard:

- Centro de alertas actuales: auditorías fuera de fecha prevista, compromisos PAC vencidos, informes pendientes, expedientes sin responsable, fases sin movimiento por 14 días y brechas abiertas de riesgo alto/crítico. El centro usa filtros de dominio/unidad/auditor, pero no se recorta por el rango histórico seleccionado.
- Flujo de auditorías por fase y carga asignada por auditor. Los números representan casos asignados y edades de calendario, no horas activas de trabajo.
- Controles agregados de calidad: auditorías abiertas sin equipo/cédulas, cierres sin fecha real, diferencia entre criterios e ítems y vínculos de observación a ítems cruzados entre expedientes. Las observaciones generales sin item_id se clasifican como informativas válidas.
- Exportación real a PDF (ReportLab) e informe HTML imprimible para el navegador.
- Hoja Excel con alertas, calidad, flujo/carga y cortes históricos, además de las hojas previas y gráficos.
- Cortes inmutables y mediciones KPI con histórico consultable.

### Migración 015

Aplicar `sql/015_contralor_snapshots.sql` después de la 014. Es aditiva: crea `analytics.dashboard_snapshots` y `analytics.kpi_measurements`; la aplicación solo recibe `SELECT` e `INSERT` para estas tablas. No cambia tablas de auditorías, cédulas, observaciones ni informes.

### Instalación local

El instalador asociado comprueba hashes de los archivos actuales del dashboard, realiza copia de seguridad y soporta `--dry-run` y `--apply`; no ejecuta SQL ni Docker. Tras aplicar, ejecutar sintaxis, tests y revisión de diff. Después de migración 015, reconstruir la imagen API y hacer `up -d --no-deps api`, verificar los endpoints.

### Cortes periódicos y reporte mensual

`python scripts/capture_contralor_snapshot.py` crea un corte agregado automático (origen `AUTOMATICO`).
`python scripts/generate_contralor_monthly_report.py` guarda un Excel y un informe HTML imprimible para el mes calendario anterior en `/srv/data/engagement/contralor-reports` (volumen persistente del contenedor API). El HTML se puede abrir e imprimir/guardar como PDF. Los scripts están listos para ser llamados por un planificador local; la tarea programada no queda activada automáticamente por el instalador.

### Límites de interpretación

- Una brecha registrada no implica que todos los criterios de una cédula hayan sido evaluados.
- Observaciones generales sin criterio asociado están permitidas y no se clasifican como error por sí solas.
- Los tiempos de fase y la antigüedad son tiempos de calendario. El cronómetro de actividad mide intervalos activos declarados con inicio/pausa/reanudación/finalización; no mide teclas ni prueba productividad.
- Las alertas de fase sin movimiento usan 14 días como umbral operativo fijo inicial; conviene parametrizarlo posteriormente si la institución define otro SLA.
- Un corte histórico conserva el estado agregado existente en el momento de captura, no reconstituye lo que sucedió antes de habilitar la función.


### PDF real

El endpoint `GET /api/v1/analytics/contralor/export.pdf` genera un PDF descargable con comparación de dominios, alertas, calidad de datos, flujo, carga y KPI. El paquete añade `reportlab>=4.4,<5` a `requirements/base.txt` si no existe ya otra declaración. El informe HTML imprimible se mantiene como alternativa.


### Activar capturas diarias e informe mensual en macOS (opcional)

Después de aplicar migración 015, instalar la imagen de API nueva y comprobar que las tareas se ejecutan una vez manualmente, se pueden instalar dos LaunchAgents del usuario:

```bash
chmod +x scripts/install_contralor_monthly_launch_agent.sh
./scripts/install_contralor_monthly_launch_agent.sh install
```

Se guarda un corte diario a las 23:50 y se genera el informe Excel/PDF/HTML del mes anterior el día 1 a las 07:10, según el reloj local del Mac. Requiere que Docker Desktop y los servicios SICAS estén iniciados; se revisan los logs bajo `~/SICAS-backups/contralor-*.log`. Para eliminar ambas tareas:

```bash
./scripts/install_contralor_monthly_launch_agent.sh uninstall
```

El instalador del paquete no activa estos trabajos de forma automática; la instalación de una tarea recurrente del sistema operativo queda como decisión explícita del administrador.


## Registro de actividad activa del auditor (migración 016)

La ampliación incorpora una página independiente **Registro de actividad**, accesible a usuarios con `audit:manage`. Solo permite iniciar una sesión en una auditoría que esté asignada al usuario, en curso y en Trabajo de campo o Informe. El propietario puede pausar, reanudar y finalizar su propia sesión; el histórico finalizado se vuelve inmutable. Cada transición se intenta registrar también en la bitácora canónica. La tabla impide más de una sesión abierta por usuario.

Estas horas son intervalos activos declarados por el auditor mediante el cronómetro; no son una medición de teclado, presencia física o productividad y requieren que la persona pause el contador cuando deja de trabajar. El dashboard agrega las horas por auditor según la fecha de inicio de sesión dentro del período elegido. Las sesiones anteriores a la activación no se reconstruyen retrospectivamente.

Aplicar `sql/016_auditor_activity_tracking.sql` después de la migración 015 y antes de reconstruir la API.
