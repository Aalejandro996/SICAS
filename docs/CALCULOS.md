# Cálculos y conciliación

Todos los importes se manejan con `Decimal` (módulo `analytics/calculations.py`). Con `float`, `0.1 + 0.2` da `0.30000000000000004`; en una contraloría esas diferencias se acumulan y no concilian.

## Convenciones (validar con el área actuarial y la normativa vigente)

| Tema | Convención adoptada |
|---|---|
| Redondeo | 2 decimales, `ROUND_HALF_UP` (2,675 → 2,68), solo al resultado final, sin redondeos intermedios |
| Vigencia | Semiabierta `[inicio, fin)`; días totales = `fin − inicio` |
| Prima devengada | `prima × días_transcurridos / días_totales`, limitada entre 0 y la prima |
| Reserva de prima no devengada | `prima − devengada` (pro-rata por días exactos) |
| Siniestros incurridos | `pagados + reserva final − reserva inicial` |
| Moneda | Nunca se suman monedas distintas; la conversión exige una tasa explícita y positiva |
| Divisor cero | El indicador devuelve `None`, no un valor inventado |

## Fórmulas disponibles

| Indicador | Cálculo |
|---|---|
| Siniestralidad | incurridos / prima devengada |
| Ratio de gastos | gastos / prima devengada |
| Ratio combinado | (incurridos + gastos) / prima devengada |
| Severidad | monto de siniestros / n.º de siniestros |
| Frecuencia | n.º de siniestros / pólizas expuestas |
| Variación | absoluta (real − esperado) y porcentual (sobre el esperado) |

Ejemplo verificado en las pruebas: prima 1.000 con vigencia de 365 días; al día 73 la devengada es 200,00 y la no devengada 800,00. Con pagados 600, reserva inicial 200 y final 300, los incurridos son 700 y la siniestralidad 0,7000.

## Conciliación de cargas

Cada carga calcula, sobre las filas válidas leídas del archivo: cantidad, **monto por moneda** y un **hash independiente del orden**. Después de promover a las tablas finales se compara con lo realmente cargado: **tolerancia cero**. Si hay diferencia, la carga queda en `FAILED`, no dispara el motor y se registra `INGESTION_RECONCILIATION_FAILED`.

## Qué falta

- No se implementaron las fórmulas regulatorias de **margen de solvencia, reservas matemáticas, IBNR ni inversiones**: dependen de la metodología aprobada por la SUDEASEG y deben definirse con el actuario responsable.
- Los KPIs técnicos de siniestralidad requieren los datasets de **siniestros pagados** y **gastos**, que todavía no existen. `GET /analytics/overview` muestra solo indicadores de control (hallazgos abiertos, cargas y conciliación).
- Las tasas de cambio (BCV u otra fuente) deben cargarse como tabla fechada; hoy solo existe la operación de conversión con tasa explícita.
