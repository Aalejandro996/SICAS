-- 034: restablecimiento de contraseña por el Administrador con doble verificación.
-- La contraseña temporal se guarda cifrada (AES-256-GCM en la aplicación) solo hasta que el
-- Administrador que la solicitó la consulta una vez; después se elimina.
ALTER TABLE admin.action_requests DROP CONSTRAINT IF EXISTS action_requests_action_check;
ALTER TABLE admin.action_requests ADD CONSTRAINT action_requests_action_check
    CHECK (action IN ('SECURITY_POLICY','REVOKE_SESSIONS','DEACTIVATE_USER','ACCESS_REVIEW','SMTP_TEST','RESET_PASSWORD'));
ALTER TABLE admin.action_requests ADD COLUMN IF NOT EXISTS secret_enc TEXT;
ALTER TABLE admin.action_requests ADD COLUMN IF NOT EXISTS secret_viewed_at TIMESTAMPTZ;
