# Firma electrónica y sellado de tiempo de dictámenes

## Objetivo

Que cada dictamen o providencia se emita como un PDF cuya integridad, autoría y fecha puedan verificarse de forma independiente, de modo que se sustente su validez conforme a la Ley de Mensajes de Datos y Firmas Electrónicas.

## Flujo

```
Redactor (Auditor) → SUBMITTED → Aprobador (Contralor ≠ redactor) → APPROVED [hash del contenido fijado]
      → Firma (Contralor, MFA reciente) → PDF PAdES + sello de tiempo → SIGNED [registro + audit trail]
```

## Controles implementados

| Control | Dónde |
|---|---|
| Máquina de estados; no se pueden saltar pasos | `reporting/workflow.py` |
| Doble control: redactor ≠ aprobador ≠ firmante; restricción `CHECK` en BD | `workflow.py`, `sql/002` |
| Hash canónico del contenido al aprobar; si cambia, se exige nueva aprobación | `workflow.body_hash`, `can_sign` |
| Permiso `report:sign` solo para Contralor + MFA reciente (≤ 5 min) | `rbac.permission_required(step_up=True)` |
| PDF determinista (mismo contenido, mismo texto) con huella impresa | `reporting/dictamen_pdf.py` |
| Firma PAdES SHA-256, campo visible, firma incremental | `signing/service.py` (pyHanko) |
| Sello de tiempo RFC 3161 de una TSA configurable (nivel B-T) | `sign_pdf(tsa_url=...)` |
| Clave en PKCS#12 (pruebas) o HSM/token PKCS#11 (producción) | `signing.load_signer` |
| Registro solo-inserción de: hash sin firma, hash firmado, certificado, serial, fecha, TSA | `reporting.signed_documents` |
| Verificación independiente: integridad, cadena de confianza, cobertura total, sello | `signing/verify.py`, `POST /reports/verify` |
| Cada paso (envío, aprobación, rechazo, firma, verificación) queda en el audit trail | `reporting/api.py` |

## Puesta en marcha

1. Obtener el certificado de firma del Contralor de un **Proveedor de Servicios de Certificación acreditado ante SUSCERTE** (confirmar con Legal el nivel de firma requerido).
2. Guardar la clave en HSM/token. Solo para pruebas: PKCS#12 fuera del repositorio, con la contraseña en un secreto del orquestador.
3. Definir `TSA_URL` de una autoridad de sellado de tiempo reconocida y `SIGNING_TRUST_ROOTS_PEM` con las raíces de confianza.
4. Configurar retención WORM (bloqueo de objetos) en el bucket `signed/`.
5. Ejecutar `python -m unittest tests.integration.test_signing_roundtrip -v` en un entorno con las dependencias instaladas.

## Limitaciones

- La firma usa pyHanko; el código de integración **no se pudo ejecutar** en el entorno donde se elaboró (sin acceso a instalar dependencias). La prueba `test_signing_roundtrip` está incluida y debe ejecutarse antes de cualquier uso.
- La validez jurídica depende del certificado, de la TSA y de la política de Legal; el software por sí solo no la otorga.
- No se implementa aún validación a largo plazo (PAdES-LTV) con OCSP/CRL embebidos; se recomienda para documentos con conservación de años.
- Verificar el sello y la revocación requiere acceso de red a la TSA/OCSP desde el entorno de verificación.
