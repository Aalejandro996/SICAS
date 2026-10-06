# SICAS — Sistema Integral de Contraloría y Auditoría de Seguros

Plataforma de contraloría y auditoría para una aseguradora venezolana: Flask + PostgreSQL + Celery/Redis. Incluye autenticación con MFA, RBAC con segregación de funciones y doble control, audit trail inmutable con anclaje firmado, ingesta masiva con conciliación, motor de anomalías, fraude y LC/FT, cálculos con `Decimal` y firma electrónica de dictámenes.

**Estado:** preliminar, v0.2. Elaborado por Adrian Muñoz | Auditor de Sistema.

## Para empezar

Lee **[docs/INICIO.md](docs/INICIO.md)** (guía paso a paso para levantar SICAS en desarrollo).

```bash
pip install -r requirements/dev.txt
python -m unittest discover -s tests -t . -v      # pruebas
python scripts/init_env.py                        # .env de desarrollo con claves aleatorias
```

## Contenido

| Ruta | Descripción |
|---|---|
| `INFORME_PRELIMINAR_SICAS.docx` | Informe consolidado v0.2 |
| `app/` | Código: `core/` (seguridad, cifrado, auditoría, integridad), `modules/` (auth, admin, ingestion, audit_engine, compliance, reporting, analytics), `tasks/` (Celery), `static/` (consola web) |
| `sql/` | `000` roles · `001` IAM y audit trail · `002` negocio, motor, informes · `003` seed RBAC (generado) · `004` auth, doble control, integridad · `005` privilegios |
| `docs/` | Inicio, arquitectura, seguridad, usuarios, cálculos, motor de reglas, firma, RBAC, checklist |
| `scripts/` | `init_env.py`, `bootstrap_admin.py`, `generate_rbac_seed.py` |
| `infra/` | Dockerfile, compose de referencia, Nginx (TLS 1.3) |
| `tests/` | Unitarias, de seguridad e integración |

## Estado y limitaciones

Los scripts SQL, la capa HTTP (Flask con JWT/cookies) y el módulo de firma **no se han ejecutado** contra PostgreSQL, un navegador ni pyHanko reales; la lógica de negocio (autenticación, usuarios, motor de reglas, cálculos, conciliación, integridad) sí tiene pruebas automáticas. Ver el informe, sección de verificación.
