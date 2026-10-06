# Seguridad e integridad de SICAS

## Flujo de autenticación

```
Usuario + contraseña ─▶ [bloqueo / hash Argon2id / tiempo igualado] ─▶ token "challenge" (5 min, sin permisos)
   ├─ clave temporal ─▶ cambio de contraseña (política + historial de 5) ─▶ nuevo challenge
   ├─ sin MFA ───────▶ alta TOTP (secreto cifrado AES-256-GCM) ─▶ confirmar código ─▶ sesión
   └─ con MFA ───────▶ código TOTP (±1 paso, sin reutilización) ─▶ sesión
Sesión = cookie access (10 min, HttpOnly, SameSite=Strict, CSRF doble envío) + cookie refresh (8 h, rota en cada uso)
```

## Controles por capa

| Control | Implementación | Pruebas |
|---|---|---|
| Hash de contraseñas | Argon2id (64 MiB, 3 iteraciones) | — (requiere `argon2-cffi`) |
| Política de contraseñas | ≥ 12 caracteres, 3 de 4 clases, sin datos personales, sin repetición, historial de 5 | `test_auth` |
| Enumeración de usuarios | Mensaje único; hash de relleno para usuarios inexistentes; cuenta bloqueada o inactiva = mismo mensaje | `test_auth` |
| Bloqueo | 5 fallos (contraseña **o** MFA) → 30 min; se duplica en cada reincidencia (máx. ×16) | `test_auth` |
| MFA | TOTP RFC 6238 propio; contrastado con los vectores del RFC; ventana ±1; un código no se puede reutilizar | `test_auth` |
| Secretos MFA | AES-256-GCM, ligado al usuario (AAD) y con rotación de claves | `test_auth` |
| Refresh tokens | Familias con detección de reutilización: un token usado dos veces revoca toda la sesión | `test_auth` |
| Sesión y CSRF | Cookies HttpOnly + Strict; CSRF de doble envío; permisos recalculados al rotar | revisión |
| Step-up | Firmar, aprobar roles, crear usuarios, resetear MFA, cerrar hallazgos: MFA de ≤ 5 min | `rbac.py` |
| Autorización | Permisos por rol, segregación de funciones (9 pares), doble control en roles | `test_permissions`, `test_admin` |
| Inyección SQL | Parámetros enlazados; nombres de columna solo de lista blanca | `test_lcft_ingestion` |
| Logs | JSON; redacción de cédula/RIF, correos, tokens, contraseñas y números largos | `test_lcft_ingestion` |
| Audit trail | Hash encadenado (UTC, definición única), inmutable, verificación recalculada en SQL, anclaje firmado Ed25519 | `test_integrity` + SQL sin ejecutar |
| Integridad de datos | Totales de control con `Decimal` (registros, montos por moneda, hash independiente del orden); tolerancia cero | `test_lcft_ingestion` |

## Modelo de amenazas (STRIDE)

| Amenaza | Ejemplo | Mitigación | Riesgo residual |
|---|---|---|---|
| **S**uplantación | Robo de credenciales | Argon2id, MFA obligatorio, bloqueo, TOTP sin reutilización | Phishing en tiempo real del TOTP; considerar WebAuthn |
| | Robo de la cookie de sesión | HttpOnly, Strict, expiración corta, rotación con detección de reutilización | Malware en el equipo del usuario |
| **M**anipulación | Alterar el audit trail | Triggers, hash encadenado, rol de solo inserción, anclajes firmados fuera de la BD | Superusuario con acceso al servidor de BD **y** a la clave de anclaje |
| | Alterar un dictamen firmado | PAdES + sello de tiempo; hash registrado en tabla de solo inserción | Pendiente validar con certificado real |
| | Alterar la carga masiva | Hash del archivo, totales de control, rechazos trazados | — |
| **R**epudio | "Yo no aprobé eso" | Audit trail con actor, IP, roles y request_id; step-up de MFA; doble control | — |
| | Acceso indebido a datos | RBAC mínimo; SYS_ADMIN sin datos de negocio; GERENCIA solo agregados | Cifrado de columnas de negocio **pendiente** |
| **D**enegación | Fuerza bruta / inundación | Límites por IP y por usuario, Nginx, tamaño máximo de carga | Falta WAF y límite global |
| **E**scalada | Autoasignarse roles | Prohibido por BD y servicio; doble control; SoD; último administrador protegido | Un SYS_ADMIN y un CONTRALOR en colusión |

## Gestión de claves

- **Anillo de claves AES** (`SICAS_KEYS`): agregar una clave nueva, ponerla como `SICAS_ACTIVE_KEY`; las antiguas siguen descifrando. `KeyRing.needs_rotation()` indica qué registros reencriptar.
- **Clave de anclaje Ed25519**: la privada solo en el worker (idealmente HSM); la pública en un lugar distinto al de la base de datos.
- **JWT_SECRET_KEY / SECRET_KEY**: rotarlas invalida todas las sesiones.
- Producción: Vault o secretos del orquestador; nunca `.env`.

## Brechas conocidas (no implementado)

1. Cifrado de columnas de negocio (cédula/RIF) con índice ciego: `crypto.py` está listo; falta aplicarlo en las tablas.
2. Códigos de respaldo de MFA (tabla y generador previstos; falta el flujo de uso).
3. WebAuthn/FIDO2 como segundo factor resistente a phishing.
4. Pruebas de integración de la capa Flask (JWT, cookies, CSRF): la capa HTTP se revisó, pero no se pudo ejecutar.
5. Pruebas de penetración, SAST/SCA y revisión externa.
