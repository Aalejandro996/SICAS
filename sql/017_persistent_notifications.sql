-- SICAS - Migración 017: notificaciones persistentes por usuario.
-- Aditiva e idempotente. No cambia roles, expedientes, informes ni estados de workflow.
BEGIN;

CREATE TABLE IF NOT EXISTS iam.user_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recipient_user_id UUID NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
    actor_user_id UUID REFERENCES iam.users(id) ON DELETE SET NULL,
    category VARCHAR(16) NOT NULL CHECK (category IN ('REPORT','ROLE','SYSTEM')),
    event_key VARCHAR(240) NOT NULL,
    title VARCHAR(180) NOT NULL,
    message TEXT NOT NULL,
    target_path VARCHAR(500) NOT NULL DEFAULT '#/notifications',
    entity_type VARCHAR(40),
    entity_id VARCHAR(120),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    read_at TIMESTAMPTZ,
    attended_at TIMESTAMPTZ,
    UNIQUE (recipient_user_id, event_key),
    CHECK (attended_at IS NULL OR read_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_user_notifications_recipient_created
    ON iam.user_notifications(recipient_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_notifications_unread
    ON iam.user_notifications(recipient_user_id, created_at DESC)
    WHERE read_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_user_notifications_unattended
    ON iam.user_notifications(recipient_user_id, created_at DESC)
    WHERE attended_at IS NULL;

GRANT SELECT, INSERT, UPDATE ON iam.user_notifications TO app_rw;
COMMIT;
