-- 005: Privilegios mínimos. Ejecutar como propietario después de 001-004.
-- app_rw: aplicación y workers.  audit_reader: consulta del audit trail (solo lectura).
GRANT USAGE ON SCHEMA iam, insurance, engine, reporting, staging, compliance TO app_rw;

GRANT SELECT, INSERT, UPDATE ON iam.users, iam.mfa_devices, iam.refresh_tokens, iam.role_change_requests TO app_rw;
GRANT SELECT, INSERT ON iam.user_roles, iam.password_history TO app_rw;
GRANT DELETE ON iam.user_roles TO app_rw;                 -- retiro de rol (aprobado), queda en el audit trail
GRANT SELECT ON iam.roles, iam.permissions, iam.role_permissions, iam.sod_conflicts TO app_rw;

GRANT SELECT, INSERT, UPDATE ON insurance.ingestion_jobs TO app_rw;
GRANT SELECT, INSERT ON insurance.policies, insurance.claims, insurance.reserves, insurance.payments,
                        insurance.ingestion_rejects TO app_rw;   -- sin UPDATE/DELETE: copia fiel de lo recibido
GRANT SELECT, INSERT, DELETE ON staging.policies, staging.claims, staging.reserves, staging.payments TO app_rw;

GRANT SELECT, INSERT, UPDATE ON engine.rule_parameters, engine.runs, engine.findings TO app_rw;
GRANT SELECT, INSERT, UPDATE ON reporting.reports TO app_rw;
GRANT SELECT, INSERT ON reporting.signed_documents TO app_rw;
GRANT SELECT, INSERT, UPDATE ON compliance.watchlist TO app_rw;

GRANT USAGE ON ALL SEQUENCES IN SCHEMA iam, insurance, engine, reporting, staging, compliance TO app_rw;
GRANT USAGE ON SCHEMA audit TO audit_reader;
