from __future__ import annotations

import uuid

from sqlalchemy import text

from app.extensions import db
from .service import AdminUser, RemovalRequest, RoleRequest


def _rid(code: str) -> int:
    return db.session.execute(text("SELECT id FROM iam.roles WHERE code=:c"), {"c": code}).scalar_one()


class SqlAdminRepo:
    def find_by_username(self, username):
        return self._one("u.username = :v", {"v": username})

    def get_user(self, user_id):
        return self._one("u.id = CAST(:v AS uuid)", {"v": user_id})

    def _one(self, where, params):
        r = db.session.execute(text(
            "SELECT u.id::text, u.username, u.is_active, COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') roles "
            "FROM iam.users u LEFT JOIN iam.user_roles ur ON ur.user_id=u.id LEFT JOIN iam.roles r ON r.id=ur.role_id "
            f"WHERE {where} GROUP BY u.id"), params).first()
        return AdminUser(r.id, r.username, r.is_active, list(r.roles)) if r else None

    def list_users(self):
        rows = db.session.execute(text(
            "SELECT u.id::text, u.username, u.email, u.full_name, u.is_active, u.locked_until, u.last_login_at, "
            "COALESCE(array_agg(r.code) FILTER (WHERE r.code IS NOT NULL), '{}') roles FROM iam.users u "
            "LEFT JOIN iam.user_roles ur ON ur.user_id=u.id LEFT JOIN iam.roles r ON r.id=ur.role_id "
            "WHERE u.removed_at IS NULL GROUP BY u.id ORDER BY u.username")).all()
        return [dict(r._mapping) for r in rows]

    def create_user(self, username, email, full_name, password_hash, created_by):
        uid = str(uuid.uuid4())
        db.session.execute(text("INSERT INTO iam.users (id, username, email, full_name, password_hash, created_by, must_change_password) "
                                "VALUES (CAST(:i AS uuid), :u, :e, :n, :h, CAST(:c AS uuid), true)"),
                           {"i": uid, "u": username, "e": email, "n": full_name, "h": password_hash, "c": created_by})
        db.session.commit()
        return uid

    def set_active(self, user_id, active):
        db.session.execute(text("UPDATE iam.users SET is_active=:a WHERE id=CAST(:i AS uuid)"), {"a": active, "i": user_id})
        db.session.commit()

    def count_active_with_role(self, role):
        return db.session.execute(text("SELECT count(*) FROM iam.user_roles ur JOIN iam.roles r ON r.id=ur.role_id "
                                       "JOIN iam.users u ON u.id=ur.user_id WHERE r.code=:c AND u.is_active"), {"c": role}).scalar_one()

    def add_role(self, user_id, role, granted_by, approved_by):
        db.session.execute(text("INSERT INTO iam.user_roles (user_id, role_id, granted_by, approved_by) "
                                "VALUES (CAST(:u AS uuid), :r, CAST(:g AS uuid), CAST(:a AS uuid))"),
                           {"u": user_id, "r": _rid(role), "g": granted_by, "a": approved_by})

    def remove_role(self, user_id, role):
        db.session.execute(text("DELETE FROM iam.user_roles WHERE user_id=CAST(:u AS uuid) AND role_id=:r"),
                           {"u": user_id, "r": _rid(role)})

    def create_request(self, q: RoleRequest):
        db.session.execute(text("INSERT INTO iam.role_change_requests (id, target_user_id, role_id, action, reason, requested_by) "
                                "VALUES (CAST(:i AS uuid), CAST(:t AS uuid), :r, :a, :why, CAST(:b AS uuid))"),
                           {"i": q.id, "t": q.target_user_id, "r": _rid(q.role), "a": q.action, "why": q.reason, "b": q.requested_by})
        db.session.commit()

    def get_request(self, request_id):
        r = db.session.execute(text("SELECT q.id::text, q.target_user_id::text, ro.code role, q.action, q.reason, "
                                    "q.requested_by::text, q.status FROM iam.role_change_requests q JOIN iam.roles ro ON ro.id=q.role_id "
                                    "WHERE q.id=CAST(:i AS uuid) FOR UPDATE"), {"i": request_id}).first()
        return RoleRequest(r.id, r.target_user_id, r.role, r.action, r.reason, r.requested_by, r.status) if r else None

    def list_requests(self, status="PENDING"):
        rows = db.session.execute(text(
            "SELECT q.id::text, t.username target, ro.code role, q.action, q.reason, b.username requested_by, q.status, q.created_at "
            "FROM iam.role_change_requests q JOIN iam.users t ON t.id=q.target_user_id JOIN iam.users b ON b.id=q.requested_by "
            "JOIN iam.roles ro ON ro.id=q.role_id WHERE q.status=:s ORDER BY q.created_at"), {"s": status}).all()
        return [dict(r._mapping) for r in rows]

    def pending_exists(self, target, role, action):
        return db.session.execute(text("SELECT 1 FROM iam.role_change_requests WHERE target_user_id=CAST(:t AS uuid) "
                                       "AND role_id=:r AND action=:a AND status='PENDING'"), {"t": target, "r": _rid(role), "a": action}).first() is not None

    def decide_request(self, request_id, status, decided_by, note):
        db.session.execute(text("UPDATE iam.role_change_requests SET status=:s, decided_by=CAST(:d AS uuid), decided_at=now(), "
                                "decision_note=:n WHERE id=CAST(:i AS uuid)"), {"s": status, "d": decided_by, "n": note, "i": request_id})
        db.session.commit()                     # confirma también add_role/remove_role de la misma transacción

    def revoke_sessions(self, user_id):
        db.session.execute(text("UPDATE iam.refresh_tokens SET revoked_at=now() WHERE user_id=CAST(:u AS uuid) AND revoked_at IS NULL"), {"u": user_id})

    def unlock(self, user_id):
        db.session.execute(text("UPDATE iam.users SET failed_attempts=0, locked_until=NULL, lockouts=0 WHERE id=CAST(:u AS uuid)"), {"u": user_id})
        db.session.commit()

    def reset_mfa(self, user_id):
        db.session.execute(text("DELETE FROM iam.mfa_devices WHERE user_id=CAST(:u AS uuid)"), {"u": user_id})
        db.session.execute(text("UPDATE iam.users SET mfa_last_step=NULL WHERE id=CAST(:u AS uuid)"), {"u": user_id})
        db.session.commit()

    # ---- baja definitiva ----
    def is_removed(self, user_id):
        return db.session.execute(text("SELECT removed_at IS NOT NULL FROM iam.users WHERE id=CAST(:u AS uuid)"),
                                  {"u": user_id}).scalar() is True

    def removal_pending(self, user_id):
        return db.session.execute(text("SELECT 1 FROM iam.user_removal_requests WHERE target_user_id=CAST(:u AS uuid) "
                                       "AND status='PENDING'"), {"u": user_id}).first() is not None

    def create_removal_request(self, q: RemovalRequest):
        db.session.execute(text("INSERT INTO iam.user_removal_requests (id, target_user_id, reason, requested_by) "
                                "VALUES (CAST(:i AS uuid), CAST(:t AS uuid), :r, CAST(:b AS uuid))"),
                           {"i": q.id, "t": q.target_user_id, "r": q.reason, "b": q.requested_by})
        db.session.commit()

    def get_removal_request(self, request_id):
        r = db.session.execute(text("SELECT id::text, target_user_id::text, reason, requested_by::text, status "
                                    "FROM iam.user_removal_requests WHERE id=CAST(:i AS uuid) FOR UPDATE"), {"i": request_id}).first()
        return RemovalRequest(r.id, r.target_user_id, r.reason, r.requested_by, r.status) if r else None

    def list_removal_requests(self, status="PENDING"):
        rows = db.session.execute(text(
            "SELECT q.id::text, t.username target, t.full_name target_name, q.reason, b.username requested_by, q.status, "
            "q.created_at, d.username decided_by, q.decided_at, q.decision_note FROM iam.user_removal_requests q "
            "JOIN iam.users t ON t.id=q.target_user_id JOIN iam.users b ON b.id=q.requested_by "
            "LEFT JOIN iam.users d ON d.id=q.decided_by WHERE q.status=:s ORDER BY q.created_at DESC LIMIT 200"), {"s": status}).all()
        return [dict(r._mapping) for r in rows]

    def remove_user(self, user_id, removed_by, reason):
        db.session.execute(text("DELETE FROM iam.user_roles WHERE user_id=CAST(:u AS uuid)"), {"u": user_id})
        db.session.execute(text("UPDATE iam.users SET is_active=false, removed_at=now(), removed_by=CAST(:b AS uuid), "
                                "removal_reason=:r WHERE id=CAST(:u AS uuid)"), {"u": user_id, "b": removed_by, "r": reason})

    def decide_removal(self, request_id, status, decided_by, note):
        db.session.execute(text("UPDATE iam.user_removal_requests SET status=:s, decided_by=CAST(:d AS uuid), decided_at=now(), "
                                "decision_note=:n WHERE id=CAST(:i AS uuid)"), {"s": status, "d": decided_by, "n": note, "i": request_id})
        db.session.commit()                     # confirma también remove_user/revoke_sessions de la misma transacción
