"""Implementaciones SQL de UserRepo y RefreshStore (SQL parametrizado; escritura atómica donde importa)."""
from __future__ import annotations

from sqlalchemy import text

from app.extensions import db

from .lockout import LoginState
from .refresh import RefreshRecord
from .service import User

_FIND = """
SELECT u.id::text, u.username, u.email, u.full_name, u.password_hash, u.is_active, u.failed_attempts,
       u.locked_until, u.lockouts, u.must_change_password, u.mfa_last_step,
       m.secret_enc, (m.confirmed_at IS NOT NULL) AS mfa_confirmed,
       COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') AS roles
FROM iam.users u
LEFT JOIN iam.mfa_devices m ON m.user_id = u.id
LEFT JOIN iam.user_roles ur ON ur.user_id = u.id
LEFT JOIN iam.roles r ON r.id = ur.role_id
WHERE {where}
GROUP BY u.id, m.secret_enc, m.confirmed_at
"""


def _to_user(r) -> User:
    return User(r.id, r.username, r.email, r.full_name, r.password_hash, r.is_active,
                LoginState(r.failed_attempts, r.locked_until, r.lockouts), r.must_change_password,
                list(r.roles), r.secret_enc, bool(r.mfa_confirmed), r.mfa_last_step)


class SqlUserRepo:
    def find_by_username(self, username):
        r = db.session.execute(text(_FIND.replace("{where}", "u.username = :v")), {"v": username}).first()
        return _to_user(r) if r else None

    def find_by_id(self, user_id):
        r = db.session.execute(text(_FIND.replace("{where}", "u.id = CAST(:v AS uuid)")), {"v": user_id}).first()
        return _to_user(r) if r else None

    def save_state(self, user_id, s):
        db.session.execute(text("UPDATE iam.users SET failed_attempts=:a, locked_until=:l, lockouts=:o WHERE id=CAST(:i AS uuid)"),
                           {"a": s.failed_attempts, "l": s.locked_until, "o": s.lockouts, "i": user_id})
        db.session.commit()

    def save_mfa(self, user_id, secret_enc, confirmed):
        db.session.execute(text(
            "INSERT INTO iam.mfa_devices (user_id, secret_enc, confirmed_at) "
            "VALUES (CAST(:u AS uuid), :s, CASE WHEN :c THEN now() END) "
            "ON CONFLICT (user_id) DO UPDATE SET secret_enc = EXCLUDED.secret_enc, "
            "confirmed_at = CASE WHEN :c THEN COALESCE(iam.mfa_devices.confirmed_at, now()) END"),
            {"u": user_id, "s": secret_enc, "c": confirmed})
        db.session.commit()

    def set_mfa_last_step(self, user_id, step):
        db.session.execute(text("UPDATE iam.users SET mfa_last_step=:s, last_login_at=now() WHERE id=CAST(:i AS uuid)"), {"s": step, "i": user_id})
        db.session.commit()

    def set_password(self, user_id, password_hash):
        db.session.execute(text("UPDATE iam.users SET password_hash=:h, password_changed_at=now(), must_change_password=false "
                                "WHERE id=CAST(:i AS uuid)"), {"h": password_hash, "i": user_id})
        db.session.commit()

    def password_history(self, user_id, n):
        rows = db.session.execute(text("SELECT password_hash FROM iam.password_history WHERE user_id=CAST(:i AS uuid) "
                                       "ORDER BY created_at DESC LIMIT :n"), {"i": user_id, "n": n}).all()
        return [r.password_hash for r in rows]

    def add_password_history(self, user_id, password_hash):
        db.session.execute(text("INSERT INTO iam.password_history (user_id, password_hash) VALUES (CAST(:i AS uuid), :h)"),
                           {"i": user_id, "h": password_hash})
        db.session.commit()


def load_permissions(user_id: str) -> list[str]:
    rows = db.session.execute(text(
        "SELECT DISTINCT p.code FROM iam.user_roles ur JOIN iam.role_permissions rp ON rp.role_id = ur.role_id "
        "JOIN iam.permissions p ON p.id = rp.permission_id WHERE ur.user_id = CAST(:u AS uuid)"), {"u": user_id}).all()
    return sorted(r.code for r in rows)


class SqlRefreshStore:
    def get(self, jti):
        r = db.session.execute(text("SELECT jti::text, family_id::text, user_id::text, expires_at, used_at IS NOT NULL AS used, "
                                    "revoked_at IS NOT NULL AS revoked FROM iam.refresh_tokens WHERE jti=CAST(:j AS uuid)"),
                               {"j": jti}).first()
        return RefreshRecord(r.jti, r.family_id, r.user_id, r.expires_at, r.used, r.revoked) if r else None

    def save(self, rec):
        db.session.execute(text("INSERT INTO iam.refresh_tokens (jti, user_id, expires_at, family_id) "
                                "VALUES (CAST(:j AS uuid), CAST(:u AS uuid), :e, CAST(:f AS uuid))"),
                           {"j": rec.jti, "u": rec.user_id, "e": rec.expires_at, "f": rec.family_id})
        db.session.commit()

    def mark_used(self, jti):
        """Atómico: solo una petición concurrente puede marcar el token como usado."""
        res = db.session.execute(text("UPDATE iam.refresh_tokens SET used_at=now() WHERE jti=CAST(:j AS uuid) AND used_at IS NULL"),
                                 {"j": jti})
        db.session.commit()
        return res.rowcount == 1

    def revoke_family(self, family_id):
        db.session.execute(text("UPDATE iam.refresh_tokens SET revoked_at=now() WHERE family_id=CAST(:f AS uuid) AND revoked_at IS NULL"),
                           {"f": family_id})
        db.session.commit()

    def revoke_user(self, user_id):
        db.session.execute(text("UPDATE iam.refresh_tokens SET revoked_at=now() WHERE user_id=CAST(:u AS uuid) AND revoked_at IS NULL"),
                           {"u": user_id})
        db.session.commit()
