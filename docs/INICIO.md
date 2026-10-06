# Cómo iniciar SICAS (modo desarrollo)

Guía para levantar SICAS en tu equipo. **No es una instalación de producción**: el modo `dev` relaja únicamente HTTPS y las cookies `Secure` y guarda los archivos cargados en una carpeta local sin cifrar. El resto de los controles (MFA, bloqueo, RBAC, audit trail) funciona igual.

> **Aviso.** Los scripts SQL y la capa web no se pudieron ejecutar antes de entregarte este paquete. Es normal que aparezca algún error al primer arranque: copia el mensaje completo y repórtalo para corregirlo.

## Paso 0. Requisitos

| Necesitas | Cómo comprobarlo |
|---|---|
| Python 3.12 o superior | `python --version` (en Linux/macOS puede ser `python3`) |
| Docker (Docker Desktop en Windows/macOS) abierto y funcionando | `docker --version` y `docker ps` sin errores |
| Puertos libres: 5432 (PostgreSQL), 6379 (Redis) y 8000 (SICAS) | Si ya tienes PostgreSQL instalado en el equipo, cambia `-p 5432:5432` por `-p 5433:5432` en el paso 2 y ajusta `DATABASE_URL` en el paso 5 |

## Paso 1. Descomprimir y abrir una terminal en la carpeta

Descomprime `sicas.zip`, entra a la carpeta resultante (la que contiene `README.md` y `app/`) y abre ahí una terminal. **Todos los comandos siguientes se ejecutan desde esa carpeta.**

## Paso 2. PostgreSQL y Redis

```bash
docker run -d --name sicas-db -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=contraloria -p 5432:5432 postgres:16
docker run -d --name sicas-redis -p 6379:6379 redis:7
```

Comprueba que ambos estén en ejecución (columna `STATUS` = `Up`):

```bash
docker ps
```

## Paso 3. Entorno Python e instalación

```bash
python -m venv .venv
```

Activa el entorno:

- Linux / macOS: `source .venv/bin/activate`
- Windows PowerShell: `.venv\Scripts\Activate.ps1` (si indica que la ejecución de scripts está deshabilitada: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y reintenta)
- Windows CMD: `.venv\Scripts\activate.bat`

Instala las dependencias y ejecuta las pruebas:

```bash
pip install -r requirements/dev.txt
python -m unittest discover -s tests -t . -v
```

Al final debe decir `OK` (con 1 prueba omitida si pyHanko no se instaló).

## Paso 4. Archivo de configuración con claves aleatorias

```bash
python scripts/init_env.py
```

Crea `.env` (modo `dev`) y la carpeta `secrets/`. **Guarda una copia de la línea `SICAS_KEYS` del `.env`**: sin ella no se puede descifrar el secreto MFA de los usuarios. Ninguno de los dos va a un repositorio (están en `.gitignore`).

Si cambiaste el puerto de PostgreSQL, edita `DATABASE_URL` en `.env` (por ejemplo `...@localhost:5433/contraloria`).

## Paso 5. Crear las tablas

Copia la carpeta `sql` al contenedor y ejecuta los seis scripts **en este orden** (sirve igual en Windows, Linux y macOS):

```bash
docker cp sql sicas-db:/sql
docker exec sicas-db psql -U postgres -d contraloria -v ON_ERROR_STOP=1 -f /sql/000_roles.sql
docker exec sicas-db psql -U postgres -d contraloria -v ON_ERROR_STOP=1 -f /sql/001_iam_audit.sql
docker exec sicas-db psql -U postgres -d contraloria -v ON_ERROR_STOP=1 -f /sql/002_insurance_engine_reporting.sql
docker exec sicas-db psql -U postgres -d contraloria -v ON_ERROR_STOP=1 -f /sql/003_rbac_seed.sql
docker exec sicas-db psql -U postgres -d contraloria -v ON_ERROR_STOP=1 -f /sql/004_auth_admin_integrity.sql
docker exec sicas-db psql -U postgres -d contraloria -v ON_ERROR_STOP=1 -f /sql/005_grants.sql
```

Cada uno debe terminar sin la palabra `ERROR`. Si alguno falla, **detente**: copia el mensaje completo. Para empezar de cero: `docker rm -f sicas-db`, repite el paso 2 y vuelve a este paso.

Comprobación rápida (debe listar 8 filas para `iam`):

```bash
docker exec sicas-db psql -U postgres -d contraloria -c "\dt iam.*"
```

## Paso 6. Crear los dos primeros usuarios

El sistema exige doble control para dar roles, pero al inicio nadie puede aprobar. Por eso los dos primeros usuarios se crean con un script. Deben ser **dos cuentas distintas** (la segregación de funciones impide acumular ambos roles). Cambia los datos por los reales:

```bash
python scripts/bootstrap_admin.py --username admin --email admin@empresa.com --name "Administrador SICAS" --role SYS_ADMIN
python scripts/bootstrap_admin.py --username contralor --email contralor@empresa.com --name "Contralor SICAS" --role CONTRALOR
```

Cada ejecución imprime una **contraseña temporal una sola vez: anótala**. El script solo funciona mientras el rol no tenga ningún usuario activo y deja el evento en el audit trail.

## Paso 7. Arrancar SICAS

Terminal 1 (con el entorno activado), la aplicación web:

```bash
python -m flask --app wsgi run -p 8000
```

Déjala abierta. Comprueba en el navegador:

- <http://localhost:8000/api/v1/health> debe mostrar `{"app":"SICAS","status":"ok"}`.
- <http://localhost:8000/api/v1/health/ready> debe mostrar base de datos y Redis en `ok`.

Terminal 2 (abre otra, entra a la carpeta y activa el entorno), las tareas en segundo plano. Para ingresar no son necesarias, pero sí para cargas de archivos y el motor de reglas:

```bash
celery -A celery_worker.celery worker -Q ingestion,reports,alerts -P solo --loglevel=INFO
```

## Paso 8. Primer ingreso

Abre <http://localhost:8000>.

1. Escribe el usuario (`admin`) y la **contraseña temporal** del paso 6.
2. Cambia la contraseña: mínimo 12 caracteres, con al menos 3 de 4 tipos (minúsculas, mayúsculas, números, símbolos), sin tu usuario ni nombre.
3. Configura la verificación en dos pasos: en tu teléfono abre una app autenticadora (Google Authenticator, Microsoft Authenticator, Aegis…), agrega una cuenta con **ingreso manual** y escribe la clave que muestra la pantalla. Luego escribe el código de 6 dígitos que genera la app.
4. Verás la sesión con tus roles y permisos.

En los siguientes ingresos: usuario + contraseña + código de la app. Repite el proceso con `contralor`.

## Paso 9. Verificar los controles de integridad (recomendado)

Estas tres comprobaciones confirman que el audit trail funciona como se diseñó. Si alguna no da el resultado esperado, repórtalo.

```bash
# 1) Debe mostrar los eventos de tus ingresos (LOGIN_OK, MFA_ENROLLED, BOOTSTRAP_USER_CREATED…)
docker exec sicas-db psql -U postgres -d contraloria -c "SELECT id, action, outcome, actor_username FROM audit.audit_log ORDER BY id DESC LIMIT 10;"

# 2) Debe devolver 0 filas (cadena de hashes íntegra)
docker exec sicas-db psql -U postgres -d contraloria -c "SELECT * FROM audit.verify_chain();"

# 3) Debe FALLAR con el mensaje "audit_log es inmutable: UPDATE no permitido"
docker exec sicas-db psql -U postgres -d contraloria -c "UPDATE audit.audit_log SET action = 'X' WHERE id = 1;"
```

## Uso diario

- **Detener:** `Ctrl+C` en cada terminal y `docker stop sicas-db sicas-redis`.
- **Volver a arrancar:** `docker start sicas-db sicas-redis`, activa el entorno y repite el paso 7.
- **Borrar todo y empezar de cero:** `docker rm -f sicas-db sicas-redis`, borra `.env`, `secrets/` y `data/`, y repite desde el paso 2.

## Qué puedes hacer y qué todavía no

La pantalla actual solo cubre el ingreso y muestra tu sesión. Todo lo demás está disponible **por la API** (`/api/v1/...`) hasta que se construyan las pantallas:

| Necesitas | Endpoint | Rol |
|---|---|---|
| Crear usuarios | `POST /admin/users` | SYS_ADMIN |
| Pedir un rol para alguien | `POST /admin/role-requests` | SYS_ADMIN |
| Aprobar/rechazar el rol | `POST /admin/role-requests/<id>/decision` | CONTRALOR |
| Cargar CSV | `POST /ingestion/uploads` | AUDITOR |
| Ver/gestionar hallazgos | `/engine/findings…` | AUDITOR / CONTRALOR |
| Alertas LC/FT | `/compliance/alerts` | AUDITOR / CONTRALOR |

Las llamadas con sesión deben enviar la cookie y el encabezado `X-CSRF-TOKEN` (valor de la cookie `csrf_access_token`). En desarrollo los archivos cargados se guardan en `data/uploads/` sin cifrar (nunca uses datos reales así). La firma de dictámenes requiere un certificado y una TSA (ver `FIRMA_SELLADO.md`).

**Limitaciones conocidas de la consola:** la sesión dura 10 minutos y la pantalla aún no renueva la sesión sola, así que después tendrás que ingresar de nuevo. No hay pantallas de administración.

## Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| `RuntimeError: Variable de entorno obligatoria…` | Falta `.env` o `SICAS_ENV=dev`. Ejecuta el paso 4 desde la carpeta correcta. |
| `role "app_rw" does not exist` | Se ejecutó `001` antes que `000_roles.sql`. Respeta el orden. |
| `connection refused` (5432 o 6379) | Los contenedores no están corriendo: `docker ps` / `docker start sicas-db sicas-redis`. |
| `port is already allocated` al crear el contenedor | El puerto está ocupado. Usa otro (`-p 5433:5432`) y ajusta `DATABASE_URL`. |
| `password authentication failed` | `DATABASE_URL` no coincide con la contraseña del contenedor (`dev`). |
| No guarda la sesión en el navegador | Usa `http://localhost:8000` (no HTTPS) y confirma `SICAS_ENV=dev` en `.env`. |
| `No module named …` | El entorno no está activado o falló la instalación del paso 3. |
| "Credenciales inválidas" con la clave correcta | La cuenta pudo bloquearse (5 intentos fallidos = 30 min, el doble en cada reincidencia), el código MFA se reutilizó o caducó (cada código sirve una vez; espera al siguiente) o el reloj del teléfono está desfasado. |
| `429 Too Many Requests` | Límite de intentos por minuto; espera un minuto. |
| Perdiste el dispositivo MFA | Un administrador usa `POST /admin/users/<id>/reset-mfa` y el usuario vuelve a configurarlo. |
| Una carga queda en `FAILED` | Revisa el audit trail (`INGESTION_FAILED` / `INGESTION_RECONCILIATION_FAILED`) y el log del worker. |
| `Received unregistered task` en el worker | Reinicia el worker desde la carpeta del proyecto con el entorno activado. |
