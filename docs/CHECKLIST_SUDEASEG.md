# Checklist de controles y estado de implementación — SICAS

Lista de evidencias a preparar para una revisión de la Superintendencia. Es una guía técnica, **no** sustituye el texto de las normas vigentes: validarla con Cumplimiento y Legal.

Estados: **Código** = existe en este repositorio · **Parcial** = existe una base que falta completar · **Infra** = depende de la infraestructura · **Proceso** = depende de procedimientos de la organización.

## Integridad y trazabilidad

| Control | Estado | Referencia |
|---|---|---|
| Audit trail append-only con hash encadenado y triggers de inmutabilidad | Código | `sql/001_iam_audit.sql` |
| Verificación periódica de la cadena (recalculada en SQL) y anclajes firmados Ed25519 que detectan borrado de cola | Código | `audit.verify_chain`, `core/integrity/checkpoint.py`; SQL sin ejecutar |
| Registro de quién, qué, cuándo, desde dónde y resultado (incluye accesos denegados) | Código | `core/audit/audit_service.py`, `rbac.py` |
| Exportación periódica del audit trail a almacén inmutable (WORM) | Infra | Pendiente de configurar |
| Trazabilidad de pólizas y siniestros (histórico versionado, borrado lógico) | Parcial | Tablas de solo inserción (copia fiel de lo recibido, sin UPDATE/DELETE para la app); falta versionado entre cargas |
| Sincronización horaria (NTP) y marcas de tiempo en UTC | Infra | — |
| Retención definida por normativa y evidencia de cumplimiento | Proceso | Definir plazos con Legal |

## Control de acceso

| Control | Estado | Referencia |
|---|---|---|
| Matriz RBAC documentada, mínimo privilegio | Código | `docs/RBAC_MATRIX.md`, `permissions.py` |
| Segregación de funciones (9 pares de permisos incompatibles; se valida al solicitar y al aprobar) | Código | `permissions.SOD_CONFLICTS` |
| MFA obligatorio; JWT con expiración estricta y rotación; bloqueo por intentos | Código | `modules/auth/` (TOTP RFC 6238, rotación con detección de reutilización, bloqueo progresivo); capa HTTP sin ejecutar |
| Doble control en asignación de roles | Código | `modules/admin/service.py`, restricciones `CHECK` en `iam.role_change_requests` |
| Revisión periódica de accesos con evidencia | Proceso | — |
| Accesos privilegiados (DBA/root) registrados y aprobados | Infra / Proceso | — |

## Seguridad técnica

| Control | Estado | Referencia |
|---|---|---|
| TLS 1.3 en tránsito, HSTS | Código / Infra | `infra/nginx`, `app/__init__.py` |
| Cifrado en reposo (volumen) y de columnas sensibles | Infra / Parcial | AES-256-GCM con rotación listo en `core/security/crypto.py` (usado en secretos MFA); falta aplicarlo a las columnas de negocio |
| Consultas parametrizadas (prevención de inyección SQL) | Código | Todos los repositorios |
| CSRF, CSP estricta, cabeceras de seguridad, rate limiting | Código | `app/__init__.py`, `extensions.py` |
| Validación de archivos cargados (tipo, tamaño, hash) | Código | `ingestion/api.py`, `validators.py` |
| Gestión de secretos fuera del código | Código / Infra | `.env.example`, `.gitignore` |
| Análisis de dependencias y de código (SCA/SAST) | Proceso | `pip-audit` y `bandit` en `requirements/dev.txt` |
| Pruebas de penetración periódicas con plan de remediación | Proceso | — |

## Continuidad y operación

| Control | Estado | Referencia |
|---|---|---|
| Respaldos automáticos cifrados y pruebas de restauración | Infra / Proceso | Falta tarea programada y evidencia |
| Plan de continuidad y recuperación (DRP) probado | Proceso | — |
| Gestión de cambios y ambientes separados | Proceso | — |

## Validez de informes y firma electrónica

| Control | Estado | Referencia |
|---|---|---|
| Hash de integridad del contenido aprobado | Código | `workflow.body_hash` |
| Firma PAdES y sello de tiempo | Parcial | `signing/service.py`; pendiente de prueba con pyHanko y certificado real |
| Certificado de un PSC acreditado ante SUSCERTE | Proceso | Adquisición y custodia en HSM |
| Conservación del documento firmado y verificación reproducible | Parcial | Verificador incluido; falta el almacenamiento WORM |

## Reportes regulatorios y LC/FT

| Control | Estado | Referencia |
|---|---|---|
| Reportes estándar a la SUDEASEG con parámetros versionados | Pendiente | Formatos y periodicidad por definir con Cumplimiento |
| Reglas LC/FT configurables (umbrales, fraccionamiento, lista restrictiva) | Parcial | `rules/lcft.py` (3 reglas), `compliance/api.py`; umbrales de referencia a fijar por el Oficial de Cumplimiento |
| Trazabilidad de cada alerta (generación, análisis, decisión con motivo, cierre) | Código | `compliance/api.py`; la consulta de alertas también se audita |
| Acceso restringido y confidencial a la información LC/FT | Código | Permisos `lcft:*` |
| Detección de anomalías y fraude en pólizas/siniestros/reservas | Código | `docs/AUDIT_ENGINE.md` |

## Protección de datos personales

| Control | Estado | Referencia |
|---|---|---|
| Minimización y enmascarado en pantallas y exportaciones | Parcial | GERENCIA solo ve agregados; falta el enmascarado |
| Control de descargas masivas | Parcial | Permiso `report:export`, `kpi:export`; falta límite por volumen |

## Integridad de datos y cálculos

| Control | Estado | Referencia |
|---|---|---|
| Importes con `Decimal`, redondeo definido, monedas sin mezclar | Código | `analytics/calculations.py`, `docs/CALCULOS.md` |
| Conciliación de cada carga con tolerancia cero (registros, monto por moneda, hash) | Código | `ingestion/reconcile.py` |
| Validación estricta de datos de entrada (fechas reales, montos, monedas, dominios) | Código | `ingestion/validators.py` |
| Metodología actuarial (reservas matemáticas, IBNR, margen de solvencia) | Pendiente | Definir con el actuario responsable |
