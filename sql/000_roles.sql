-- 000: Roles de base de datos. Ejecutar PRIMERO, como superusuario.
-- app_rw: lo usan la API y los workers (privilegios mínimos, ver 005).  audit_reader: consulta del audit trail.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_rw') THEN CREATE ROLE app_rw LOGIN; END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_reader') THEN CREATE ROLE audit_reader NOLOGIN; END IF;
END $$;
-- Asigne la contraseña de app_rw fuera del repositorio:   ALTER ROLE app_rw PASSWORD '<secreto>';
