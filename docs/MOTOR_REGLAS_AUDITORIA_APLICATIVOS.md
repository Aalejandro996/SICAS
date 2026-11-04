# Motor de reglas y encuestas en la auditoría de aplicativos

Guía de funcionamiento de la auditoría de aplicativos (sistemas lógicos como Acsel/x, Odoo, etc.) en SICAS: la encuesta direccionada, la evaluación, el motor de reglas que redacta los hallazgos y la retroalimentación con la que el motor propone mejoras que solo el Contralor aprueba.

Fuente de la plantilla: «Auditoria_TI_Sistema_AcselX_Matriz_Integrada_v2.xlsx» (Contraloría).
Código principal: `app/modules/engagement/` — `app_audit.py` (evaluación), `app_survey.py` (encuesta en Excel), `observation_rules.py` (redacción de hallazgos), `learning.py` (aprendizaje), `app_api.py` y `app_repo.py` (API y datos).

---

## 1. Visión general

```
Inventario de aplicativos ──► Expediente y auditoría (tipo APLICATIVO)
        │                                  │
        │                       30 controles repartidos en 8 áreas
        ▼                                  ▼
Parámetros del aplicativo        Encuestas direccionadas (una por área, Excel firmado)
(RPO, RTO, conmutación…)                   │ se devuelven y se cargan
        │                                  ▼
        └──────────────► Cédula de Sistemas (fórmula 40/30/30) ──► Panel, riesgos, madurez, pruebas
                                           │
                                           ▼
                         Motor de reglas: hallazgos automáticos por dominio
                                           │ el auditor acepta / edita / descarta
                                           ▼
                       Retroalimentación ──► propuestas de reglas ──► Contralor aprueba
```

Una auditoría de aplicativo es una auditoría de Sistemas (dominio SISTEMAS) con `audit_kind = APLICATIVO`. Usa la misma maquinaria de fases, cédulas, observaciones, evidencias e informe, más una pestaña **Aplicativo** y la sección **3.5 Evaluación del aplicativo** del informe.

---

## 2. Quién hace qué

| Paso | Quién | Permiso |
|---|---|---|
| Registrar o editar un aplicativo en el inventario | Jefe de Auditoría de Sistemas, Contralor | `audit:systems_review` / `audit:unit_manage` |
| Crear la auditoría, descargar encuestas, cargarlas, registrar pruebas, ajustar riesgos y madurez, aceptar/descartar hallazgos | Auditor (equipo de la auditoría) | `audit:manage` |
| Ver la pestaña Aplicativo | Equipo de auditoría | `audit:read` |
| Ver el motor (retroalimentación, propuestas, reglas) | Contralor, jefes, aprobador de informes | `rule:configure`, `audit:systems_review`, `audit:financial_review`, `audit:report_approve` |
| **Aprobar o rechazar propuestas y retirar reglas** | **Solo el Contralor** | `rule:configure` con verificación adicional (step-up) |
| Editar el catálogo normativo | Contralor | `rule:configure` |

---

## 3. Inventario de aplicativos

Menú **Auditoría → Inventario de aplicativos**. Cada aplicativo es una unidad (`units.kind = APLICATIVO`) con su ficha:

- Fabricante, producto, versión, motor de base de datos, alojamiento, custodio, módulos e interfaces.
- Categoría (core, ERP, contable, nómina, canal digital, otro), modelo (propio, licenciado, SaaS, nube propia) y criticidad (alta, media, baja).
- Plantilla de auditoría (hoy: `ACSELX`).
- **Parámetros** con los que se evalúan los datos medibles (editables por aplicativo):

| Parámetro | Valor por defecto | Significado |
|---|---|---|
| `rpo_min` | 15 | Pérdida máxima de datos aceptada, en minutos |
| `rto_h` | 4 | Tiempo máximo de restablecimiento, en horas |
| `failover_months` | 6 | Antigüedad máxima de la última prueba de conmutación, en meses |
| `log_review_days` | 31 | Antigüedad máxima de la última revisión de bitácoras, en días |

Al crear la auditoría de un aplicativo, el sistema arma su cédula con los controles de la plantilla (con los pesos que el Contralor haya aprobado, ver sección 9).

---

## 4. La encuesta direccionada

### 4.1 Qué es y por qué

La matriz original tiene 30 preguntas redactadas para el auditor. En vez de enviar todo a todos, cada control se dirige al **área que lo puede responder** y se reescribe en segunda persona, con la evidencia que esa área debe adjuntar. Cada área recibe su propio Excel con solo sus preguntas.

| Área destinataria | Preguntas |
|---|---|
| Administración de base de datos (DBA) | 9 |
| Seguridad de la información / Seguridad TI | 6 |
| Infraestructura y continuidad operativa | 5 |
| Desarrollo y aseguramiento de calidad (QA) | 4 |
| Usuario clave / dueño del proceso | 3 |
| Contabilidad | 1 |
| Área técnica y actuarial | 1 |
| Cumplimiento normativo | 1 |

Los 30 controles se agrupan en 6 bloques de 5 controles: **SEG** accesos, privilegios y segregación · **LOG** trazabilidad y audit trail · **BDD** criptografía y base de datos · **CHG** gestión de cambios y QA · **BCP** continuidad y DRP · **REG** integridad financiera y SUDEASEG.

### 4.2 Ciclo de uso

1. **Descargar.** En la pestaña *Aplicativo → Encuestas por área*, el auditor descarga el Excel del área (`Encuesta_<código de auditoría>_<área>.xlsx`).
2. **Enviar.** Se entrega al área (correo o canal institucional) para que lo responda.
3. **Responder.** El área completa las columnas de respuesta y los datos del respondiente.
4. **Cargar.** El auditor sube el archivo devuelto, en la fase de **Levantamiento**.
5. **Revisar.** El sistema aplica las respuestas a la cédula, guarda el archivo como evidencia (con su hash SHA-256) y muestra los avisos. El auditor valida lo marcado como inconsistente.

Se puede volver a descargar y cargar una encuesta tantas veces como haga falta; cada carga queda en la bitácora con el respondiente, el área y la cantidad de respuestas aplicadas.

### 4.3 Estructura del Excel

Hoja **Encuesta**:

- Filas 1–4: encabezado con aplicativo, auditoría y área.
- Filas 5–7: **nombre, cargo y fecha del respondiente** (columna D). Se registran como fuente de cada respuesta.
- Fila 9: encabezados. Datos desde la fila 10.

| Columna | Contenido | ¿Responde el área? |
|---|---|---|
| A–C | N°, código del control, bloque | No |
| D | Pregunta dirigida a su área | No |
| E | Evidencia que debe adjuntar | No |
| F–G | Dato solicitado y objetivo (solo controles medibles) | No |
| **H** | ¿Cumple? (Sí / No) — lista desplegable | **Sí** |
| **I** | Dato informado (número o fecha) | **Sí** (si aplica) |
| **J** | ¿Adjunta evidencia? (Sí / No) | **Sí** |
| **K** | Estado de la evidencia (Actualizado / Desactualizado / Inexistente) | **Sí** |
| **L** | Comentario | **Sí** (obligatorio si responde «No») |

Hoja oculta **`_control`**: lleva la auditoría, el área y los códigos de las preguntas, más una firma HMAC-SHA256 calculada con una clave del servidor (no se muestra ni se documenta su valor).

### 4.4 Validaciones al cargar

El archivo se rechaza si:

- no es un `.xlsx` válido, supera 5 MB o no es una encuesta generada por el sistema;
- la firma de control no coincide (archivo alterado o creado fuera de SICAS);
- pertenece a **otra auditoría**;
- no tiene ninguna respuesta.

Se aplican con aviso (no bloquean) estos casos:

- una fila con código que no pertenece a la encuesta: se ignora;
- respondió «No» sin comentario del motivo;
- el dato informado no es un número o fecha válidos.

Las celdas que empiezan con `=`, `+`, `-` o `@` se escriben como texto para evitar inyección de fórmulas.

### 4.5 Cómo se interpretan las respuestas

Cada control se guarda con tres campos: **control** (Sí/No), **documental** (¿existe soporte?) y **evidencia** (actualizada, desactualizada o inexistente).

- Si responde **No**, el soporte queda en «No» y la evidencia en «Inexistente» salvo que se indique otra cosa.
- Una fila totalmente vacía se ignora.
- Cada respuesta guarda su **fuente**: área, nombre y cargo del respondiente y fecha.

### 4.6 Dato medible e inconsistencias

Cinco controles piden un dato verificable. El sistema lo compara con el objetivo del aplicativo:

| Control | Dato que se pide | Objetivo |
|---|---|---|
| SEG03 | Cuentas genéricas o técnicas activas en producción | ≤ 0 |
| LOG05 | Fecha de la última revisión de bitácoras | No más de `log_review_days` días de antigüedad |
| BCP01 | Frecuencia del respaldo de logs transaccionales (minutos) | ≤ `rpo_min` |
| BCP03 | Fecha de la última prueba de conmutación | No más de `failover_months` meses de antigüedad |
| BCP04 | Tiempo de restablecimiento medido (horas) | ≤ `rto_h` |

Si el veredicto del dato contradice la respuesta Sí/No, la fila queda marcada como **inconsistente** para que el auditor la valide. Ejemplo: respondió «Sí» a BCP01 pero informó 30 minutos con RPO objetivo de 15 → «Respondió “Sí”, pero el dato informado (30 minutos) no cumple…». Una fecha futura se considera incumplimiento. El sistema **no corrige** la respuesta: solo avisa; la decisión es del auditor.

---

## 5. Evaluación del aplicativo

### 5.1 Puntaje de cada control (fórmula 40/30/30)

Réplica de la hoja «Cuestionario AcselX»:

| Respuesta | Puntos |
|---|---|
| Control = **No** | 0 |
| Control = **Sí** | 40 |
| + soporte documental = Sí | +30 |
| + evidencia **Actualizada** | +30 |
| + evidencia **Desactualizada** | +15 |

Máximo 100. Un control es **CONFORME** solo con *Sí + soporte + evidencia actualizada*. Un control sin responder no puntúa y no se presume brecha.

### 5.2 Cumplimiento por bloque y diagnóstico

Por bloque: conformes sobre total y promedio del puntaje. Diagnóstico por el % de cumplimiento efectivo (conformes / total): **≥ 80 % Satisfactorio**, **≥ 50 % Requiere mejora**, **< 50 % Crítico**.

Panel general: total de controles, respuestas «Sí», conformes, hallazgos, cumplimiento efectivo, promedio general, controles documentados, pendientes e inconsistencias, y avance por área.

### 5.3 Matriz de riesgos (probabilidad × impacto)

Ocho riesgos de la plantilla, cada uno atado a un control (por ejemplo, RIE-ACX-01 Segregación de funciones ← SEG04). La probabilidad e impacto se toman de dos pares según el estado del control (uno si está conforme, otro si no), y luego:

1. **Historial (motor):** ajusta la probabilidad ±1 con base en auditorías cerradas (sección 8.2).
2. **Ajuste del auditor:** puede fijar probabilidad e impacto (1 a 5) con un motivo de al menos 10 caracteres; prevalece sobre todo lo anterior y se puede restaurar.

Puntaje = probabilidad × impacto: **≥ 15 Crítico**, **≥ 10 Alto**, **≥ 5 Medio**, menos **Bajo**. El estado es «Mitigado» si el control es conforme, «Riesgo materializado» si no, y «Sin evaluar» si no tiene respuesta.

### 5.4 Pruebas técnicas

12 pruebas sustantivas: 6 sobre la base de datos (`PST-BD-01…06`: accesos DBA, cifrado en reposo, audit trail, consistencia transaccional, respaldos, cuentas de servicio) y 6 de interfaz y conciliación contable (`INT-CON-01…06`: canal cifrado, totales de control, registros huérfanos, cola de errores, edición posterior, conversión de moneda). El auditor registra por cada una: resultado (Cumple / No cumple / No aplica / Pendiente), detalle, consulta utilizada y evidencia asociada.

### 5.5 Madurez COBIT / CMMI

Seis dominios (accesos, trazabilidad, cifrado, cambios, continuidad, integridad financiera). El motor **sugiere** el nivel con el promedio del bloque: < 20 → 0 Inexistente · < 40 → 1 Inicial · < 60 → 2 Gestionado · < 80 → 3 Definido · < 95 → 4 Medible · ≥ 95 → 5 Optimizado. El auditor confirma o ajusta con una nota; el ajuste queda registrado.

### 5.6 Trazabilidad SUDEASEG y dictamen

Siete requisitos regulatorios (`TRAZ-01…07`) atados a su control, con estado Conforme / Hallazgo / Sin evaluar y su estándar internacional.

**Dictamen** del entorno de control:

| Condición | Opinión |
|---|---|
| Sin respuestas | Sin dictamen |
| Cumplimiento < 50 % **o** 3 o más riesgos críticos | **Desfavorable** |
| Algún riesgo crítico **o** cumplimiento < 80 % | **Con salvedades** |
| Resto | **Favorable** |

El texto del dictamen se redacta solo, citando bloques satisfactorios y críticos y los riesgos críticos materializados. Todo esto se incorpora al informe en la sección **3.5 Evaluación del aplicativo** (ficha, bloques, matriz de riesgos, pruebas, madurez, trazabilidad y opinión).

---

## 6. El motor de reglas: cómo redacta los hallazgos

Con la cédula respondida, el auditor pulsa **Generar observaciones de las brechas** (en el Levantamiento; en las fases siguientes el botón es **Consolidar observaciones automáticas**). El motor:

### 6.1 Detecta la brecha de cada control

| Brecha | Cuándo |
|---|---|
| **No existe** | Control = No |
| **Sin soporte documental** | Control = Sí pero sin documentación |
| **Sin evidencia de ejecución** | Evidencia inexistente |
| **Evidencia desactualizada** | Evidencia desactualizada |

Un control conforme, o sin responder, no genera hallazgo.

### 6.2 Asigna el riesgo

| Brecha | Riesgo base |
|---|---|
| No existe | ALTO |
| Sin soporte / sin evidencia | MEDIO |
| Desactualizada | BAJO |

Ajustes: un control de **peso 3** (crítico) sube un nivel; en los dominios críticos (accesos, respaldos, parches, malware, continuidad) la evidencia desactualizada sube a MEDIO.

### 6.3 Agrupa por dominio de control

Se redacta **una observación por dominio** (no una por control), con el riesgo del control más grave del grupo, la lista de controles afectados y su tipo de brecha. Cada observación trae título, condición, criterio, causa, efecto y recomendación.

- **Criterio:** se arma citando las normas de cada control desde el **catálogo normativo único** (51 normas: ISO 27001:2022, COBIT 2019, leyes venezolanas y SUDEASEG). Las referencias SUDEASEG que no se pudieron verificar contra la providencia exacta quedan marcadas **«Por validar»** hasta que el Contralor las confirme en *Motor de reglas → Normativa*.
- Las observaciones tienen la clave `sis:<dominio>` para poder aprender de ellas.
- Un control ya cubierto por una observación manual, editada o descartada **no se vuelve a redactar**.
- Las observaciones automáticas individuales que nadie editó se reemplazan por las consolidadas.

Las observaciones salen etiquetadas **«Redactada por el motor»** hasta que el auditor las acepta o las edita.

### 6.4 Auditorías de los demás dominios

El mismo motor, con su propio catálogo, redacta los hallazgos de Operativa, Financiera, Administrativa y Especial a partir de los incumplimientos por tema normativo SUDEASEG (clave `sudeaseg:<tema>`), con riesgo según la tasa de incumplimiento. Lo que se aprende (sección 8) rige para todos.

---

## 7. Decisiones del auditor sobre cada hallazgo

En la pestaña **Observaciones**, los hallazgos automáticos tienen tres acciones:

| Acción | Efecto | Qué se registra |
|---|---|---|
| **Aceptar** | Confirma la redacción del motor (queda «Motor · aceptado») | Aceptación con su autor y fecha |
| **Editar** | Corrige cualquier campo (se mantiene el historial de revisiones) | Qué campos cambió; si cambió el riesgo, también el nivel |
| **Descartar** | Retira el hallazgo con un motivo (mínimo 10 caracteres); no se vuelve a generar | El descarte y su motivo |
| **Sugerencias** | Propone causa y recomendación de hallazgos parecidos ya aprobados | — |

Otras decisiones que también alimentan el aprendizaje: cambiar el riesgo de un hallazgo, ajustar probabilidad e impacto en la matriz, ajustar la madurez y reescribir la conclusión de un informe.

---

## 8. Cómo aprende el motor

**Principio: el motor propone, nunca se modifica solo.** Todo lo que aprende queda trazado y las reglas nuevas solo se activan con aprobación expresa del Contralor.

### 8.1 Aprender de las decisiones del auditor

Cada decisión (aceptar, editar, descartar, cambiar riesgo, ajustar matriz o madurez, reescribir conclusión) se guarda en la tabla de retroalimentación, que es **solo de inserción** (un disparador impide modificarla o borrarla). Cada evento lleva el patrón al que pertenece (`sis:<dominio>`, `sudeaseg:<tema>`, `ctrl:<código>`, `madurez:<clave>`, `conclusion:<tipo>`), el valor antes y después, el motivo, el usuario y la fecha.

### 8.2 Ajuste de probabilidad con el historial de controles

Mira las últimas 5 evaluaciones cerradas de cada control (de cualquier aplicativo o auditoría):

- **+1 a la probabilidad** si falló en al menos 2 y en al menos la mitad de ellas.
- **−1** si las últimas 3 o más son todas conformes.
- Sin historial suficiente: 0.

El ajuste aparece en la matriz con su explicación («Falló en 3 de sus últimas 5 evaluaciones…»), y el auditor puede anularlo.

### 8.3 Hallazgos reiterados (todas las auditorías)

Al generar un hallazgo, el motor busca el mismo tema en las últimas auditorías **cerradas de la misma unidad**. Si lo encuentra, agrega a la condición la nota «Observación reiterada» con las auditorías involucradas; si se repite en **dos o más**, el riesgo **sube un nivel** (BAJO → MEDIO → ALTO). Queda registrado en la bitácora.

### 8.4 Sugerencia de redacción

Compara el título y la condición del hallazgo contra los de informes finales **aprobados** de otras auditorías (similitud de términos, con bonificación si es el mismo tema o control) y propone hasta 3 con su causa y recomendación. Se activa cuando existan informes aprobados de este tipo.

### 8.5 Propuestas de reglas nuevas

Al abrir las pestañas **Propuestas** o **Reglas** de *Motor de reglas*, el motor analiza los patrones (solo crea propuestas pendientes; no aplica nada). Crea una propuesta cuando un patrón se repite **al menos 3 veces**:

| Tipo | Se propone cuando | Efecto si se aprueba |
|---|---|---|
| **WEIGHT** | Un control no se cumplió en 3 o más auditorías cerradas | Sube su peso a 3 (crítico) en las cédulas nuevas |
| **RISK** (por tema) | El auditor cambió el riesgo de un tema al mismo nivel en al menos 2 de cada 3 ocasiones | El motor redacta ese tema con ese riesgo |
| **RISK** (sistémico) | Un tema aparece en 3 o más auditorías cerradas de al menos 2 unidades | Se redacta con riesgo ALTO |
| **RECOMMEND** | El auditor reescribió la recomendación de un tema 3 o más veces | Se usa la redacción más representativa como recomendación por defecto |
| **SUPPRESS** | El hallazgo de un tema fue descartado 3 o más veces y más del doble de las veces aceptado | El motor deja de redactarlo automáticamente (el auditor puede registrarlo a mano) |

Cada propuesta trae su fundamento y la lista de evidencias (auditorías, fechas y autores).

### 8.6 Aprobación por el Contralor

- Solo el Contralor aprueba o rechaza (`rule:configure`, con verificación adicional).
- Debe escribir el fundamento de su decisión (mínimo 10 caracteres).
- La aprobación crea una **regla vigente**; queda quién la aprobó y cuándo. Las reglas se pueden **retirar** (también con fundamento) y entonces dejan de aplicarse.
- Una propuesta o regla vigente no se repite.
- **Orden de aplicación:** primero el historial de la unidad (8.3) y después las reglas aprobadas, porque son decisiones expresas y prevalecen.

---

## 9. Dónde ver y operar cada cosa

**Menú Configuración → Motor de reglas** (Contralor, jefes): cuatro pestañas.

| Pestaña | Contenido |
|---|---|
| Propuestas | Propuestas pendientes con su evidencia; aprobar o rechazar |
| Retroalimentación | Todas las decisiones de los auditores, con su patrón en lenguaje legible |
| Reglas | Reglas vigentes y retiradas, con quién y cuándo |
| Normativa | Catálogo de 51 normas con su estado (Vigente / Por validar) |

**Pestaña Aplicativo** de cada auditoría: ficha, indicadores, dictamen, encuestas por área, inconsistencias, bloques, matriz de riesgos, pruebas, madurez y trazabilidad.

---

## 10. Trazabilidad y seguridad

- Cada carga de encuesta, ajuste de riesgo o madurez, prueba, aceptación, edición, descarte y aprobación de reglas se registra en la bitácora de la auditoría (`change_events`) y en el registro de auditoría del sistema, con autor, fecha y valores antes/después.
- La retroalimentación y las bitácoras son de solo inserción.
- Las encuestas llevan firma HMAC: no se aceptan archivos alterados, de otra auditoría ni de otra área.
- Las encuestas cargadas se guardan como evidencia con su hash SHA-256.
- Las reglas nuevas requieren verificación adicional (step-up) del Contralor; el motor no puede activarlas solo.
- Una falla al registrar la retroalimentación nunca bloquea el trabajo del auditor.

---

## 11. Preguntas frecuentes

**¿Puede el motor cambiar un resultado de la cédula?** No. Solo redacta hallazgos y propone reglas. Las respuestas siguen siendo las del área y las valida el auditor.

**¿Qué pasa si el área responde «Sí» pero el dato dice lo contrario?** La fila queda marcada como inconsistente; el auditor decide.

**¿Qué pasa si descarto un hallazgo del motor?** No se vuelve a generar en esa auditoría, y el descarte alimenta una posible propuesta SUPPRESS.

**¿Cuántas veces debe repetirse un patrón para que el motor proponga una regla?** Al menos 3.

**¿Puedo agregar otro aplicativo (por ejemplo, Odoo)?** Se registra en el inventario. Hoy solo existe la plantilla AcselX; para Odoo hay que cargar su propia plantilla de controles, riesgos y pruebas cuando se defina su evaluación.

**¿Cómo se agrega un nuevo catálogo de preguntas?** Con una nueva entrada en `TEMPLATES` de `app_audit.py` (controles, riesgos, pruebas, trazabilidad y madurez) y la migración que corresponda.
