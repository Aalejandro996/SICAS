# Motor de reglas de anomalías, fraude y LC/FT

## Diseño

- **Reglas independientes** (`app/modules/audit_engine/rules/`): cada una implementa `run(ctx)` y produce objetos `Finding`. Son deterministas y de solo lectura.
- **Contexto de datos** (`context.py`): las reglas no conocen SQL. `SqlContext` lee en *streaming* desde PostgreSQL; `InMemoryContext` permite probarlas sin base de datos.
- **Parámetros** (`engine.rule_parameters`): umbrales editables por el Contralor (`rule:configure`); cada corrida guarda un *snapshot* para poder reproducir el resultado.
- **Deduplicación**: cada hallazgo tiene una huella SHA-256 (`fingerprint`); re-ejecutar el motor no duplica hallazgos ya registrados.
- **Aislamiento de fallos**: si una regla falla, las demás continúan y el error queda en el resultado de la corrida.
- **Severidad y puntaje**: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`, más un puntaje 0-100 para priorizar la revisión.

## Alcance de ejecución

- La ejecución manual global requiere enviar `{"scope":"GLOBAL"}`. La interfaz pide confirmación antes de analizar todas las cargas disponibles de pólizas, siniestros, reservas y pagos.
- La ejecución manual por carga requiere `{"scope":"JOB","job_id":"<UUID>"}` y solo se admite si la carga existe y está en estado `COMPLETED`.
- Una petición vacía no activa una ejecución global de forma implícita.
- La ejecución automática disparada al completar una ingesta sigue recibiendo el `job_id` de esa carga; este contrato manual no modifica ese flujo.

## Catálogo de reglas

| Código | Qué detecta | Parámetros por defecto (punto de partida) | Severidad |
|---|---|---|---|
| `DUP-CLAIM` | Número de siniestro repetido; misma póliza + fecha + cobertura + monto con distinto número | `amount_round=2` | HIGH |
| `DUP-POLICY` | Número de póliza repetido; mismo asegurado + riesgo + ramo con vigencias solapadas | — | HIGH / MEDIUM |
| `EARLY-CLAIM` | Siniestro fuera de la vigencia; a ≤ N días del inicio de vigencia; reporte tardío | `high_days=7`, `medium_days=30`, `late_report_days=30`, `last_days=0` | CRITICAL / HIGH / MEDIUM |
| `RESERVE-RANGE` | Reserva negativa; mayor a la razón máxima de la suma asegurada; fuera del rango autorizado por ramo; atípica por z modificado | `max_ratio=1.0`, `z_threshold=3.5`, `z_high=6.0`, `min_group_size=30` | HIGH / MEDIUM |
| `BENFORD-1D` | Distribución del primer dígito de los montos que se aparta de la ley de Benford | `min_sample=300`, `min_value=10`, `min_magnitude_ratio=100` | LOW / MEDIUM / HIGH |
| `LCFT-THRESHOLD` | Pago individual igual o superior al umbral de la moneda (por defecto solo efectivo) | `thresholds={"USD":"10000"}`, `methods=["CASH"]` | HIGH |
| `LCFT-STRUCTURING` | Fraccionamiento: ≥ N pagos del mismo pagador, cada uno bajo el umbral, cuyo total en la ventana lo alcanza | `window_days=30`, `min_count=3` + umbrales | HIGH |
| `LCFT-WATCHLIST` | Asegurado o pagador presente en la lista restrictiva activa (identificador normalizado) | — | CRITICAL |

Los umbrales son valores iniciales razonables, **no** valores validados con datos de la aseguradora. Deben calibrarse por ramo con información histórica antes de usarse como evidencia. En las reglas **LC/FT** los umbrales son parámetros de referencia: el Oficial de Cumplimiento debe fijarlos conforme a la normativa vigente. Las monedas sin umbral configurado se omiten y se informan como omitidas; nunca se adivina un valor.

**Integridad de datos que el motor también controla:** un siniestro cuya póliza no existe en los datos cargados se reporta como hallazgo `EARLY-CLAIM` de tipo `HUERFANO`. Las tablas de negocio son copia fiel de lo recibido (sin unicidad impuesta) justamente para que los duplicados puedan detectarse en lugar de quedar ocultos por la base de datos.

**Monedas:** las reglas nunca mezclan monedas. Los duplicados incluyen la moneda en su firma, las reservas se comparan solo dentro de su moneda y Benford separa la distribución por moneda.

## Ley de Benford: método

1. Se toma el primer dígito significativo de cada monto ≥ `min_value`.
2. Se compara la frecuencia observada con la esperada, `log10(1 + 1/d)`.
3. Se calcula la **MAD** (desviación absoluta media) y la clasificación de Nigrini para primer dígito: ≤ 0,006 conforme; ≤ 0,012 aceptable; ≤ 0,015 marginal; > 0,015 no conforme.
4. Se informa también el chi-cuadrado (gl = 8; críticos 15,507 al 5 % y 20,090 al 1 %) y el estadístico z por dígito, para señalar qué dígitos se desvían más.
5. La severidad se basa en la MAD, no en el chi-cuadrado, porque con muestras grandes el chi-cuadrado rechaza casi siempre.
6. Se **omiten** (y se reportan como omitidos) los grupos con muestra menor a `min_sample` o cuyos montos no abarcan al menos dos órdenes de magnitud, donde Benford no aplica.

Una desviación es una **señal para dirigir el muestreo**, no una prueba de fraude: montos fijados por tarifa, deducibles, topes o redondeos legítimos también la producen.

## Contrato de campos

| Dataset | Campos requeridos |
|---|---|
| `policies` | `policy_number`, `insured_id`, `risk_id`, `branch`, `start_date`, `end_date`, `sum_insured`, `premium` |
| `claims` | `claim_number`, `policy_number`, `coverage`, `occurrence_date`, `reported_date`, `claimed_amount` |
| `reserves` | `reserve_type` (`CLAIM`/`MATHEMATICAL`/`UNEARNED_PREMIUM`), `branch`, `period`, `amount`, `sum_insured`, y `policy_number` o `claim_number` |
| `payments` | `payment_id`, `policy_number`, `payer_id`, `amount`, `currency`, `method` (`CASH`/`TRANSFER`/`CARD`/`CHECK`/`OTHER`), `paid_at` |

Todos los datasets exigen `currency` (`VES`, `USD` o `EUR`). Las columnas desconocidas del archivo se descartan.

Formato de fechas `AAAA-MM-DD`; montos con punto o coma decimal. Las filas inválidas se rechazan y se guardan con su número de línea y el motivo.

## Escalabilidad

Las reglas actuales recorren los datos en Python (aptas para cientos de miles de registros por corrida). Para volúmenes mayores, las reglas de duplicados y Benford se pueden trasladar a SQL (`GROUP BY` / `WINDOW`) en la réplica de lectura sin cambiar el contrato de `Finding`.

## Cómo agregar una regla

1. Crear la clase en `rules/` heredando de `Rule` (código, `default_params`, `run`).
2. Registrarla en `REGISTRY` (`engine.py`).
3. Añadir el ruteo de alertas en `alert_tasks.py`; sus umbrales se editan en `engine.rule_parameters` (`PUT /engine/rules/<código>`, con MFA reciente y auditoría del cambio).
4. Escribir pruebas en `tests/unit/`.
