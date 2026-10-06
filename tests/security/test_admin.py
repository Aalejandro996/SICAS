import itertools
import unittest

from app.core.security.permissions import AUDITOR, CONTRALOR, GERENCIA, SYS_ADMIN
from app.modules.admin.service import AdminError, AdminUser, RoleRequest, UserAdminService, generate_temp_password
from app.modules.auth.password import validate_password


class FakeRepo:
    def __init__(self):
        self.users, self.reqs, self.sessions_revoked, self.seq = {}, {}, [], itertools.count(1)
        self.mfa_reset, self.log = [], []

    def add(self, uid, username, roles=(), active=True):
        self.users[uid] = AdminUser(uid, username, active, list(roles))

    def find_by_username(self, n): return next((u for u in self.users.values() if u.username == n), None)
    def get_user(self, i): return self.users.get(i)
    def create_user(self, username, email, full_name, h, by):
        uid = f"n{next(self.seq)}"; self.add(uid, username); return uid
    def set_active(self, i, a): self.users[i].is_active = a
    def count_active_with_role(self, r): return sum(1 for u in self.users.values() if u.is_active and r in u.roles)
    def add_role(self, i, r, by, appr): self.users[i].roles.append(r)
    def remove_role(self, i, r): self.users[i].roles.remove(r)
    def create_request(self, q): self.reqs[q.id] = q
    def get_request(self, i): return self.reqs.get(i)
    def pending_exists(self, t, r, a): return any(q.target_user_id == t and q.role == r and q.action == a and q.status == "PENDING" for q in self.reqs.values())
    def decide_request(self, i, st, by, note): self.reqs[i].status, self.reqs[i].decided_by = st, by
    def revoke_sessions(self, i): self.sessions_revoked.append(i)
    def unlock(self, i): pass
    def reset_mfa(self, i): self.mfa_reset.append(i)


class Hasher:
    def hash(self, p): return "h:" + p
    def verify(self, h, p): return h == "h:" + p
    def needs_rehash(self, h): return False


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepo()
        self.repo.add("adm1", "admin1", [SYS_ADMIN]); self.repo.add("con1", "contralor1", [CONTRALOR])
        self.repo.add("aud1", "auditor1"); self.repo.add("adm2", "admin2", [SYS_ADMIN])
        self.ids = itertools.count(100)
        self.svc = UserAdminService(self.repo, Hasher(), lambda *a, **k: self.repo.log.append((a, k)), lambda: f"r{next(self.ids)}")

    def test_temp_password_meets_policy_and_user_has_no_roles(self):
        self.assertEqual(validate_password(generate_temp_password()), [])
        uid, temp = self.svc.create_user("adm1", "María.Gómez"[:0] + "mgomez", "m@x.com", "María Gómez")
        self.assertEqual(self.repo.users[uid].roles, [])
        with self.assertRaises(AdminError):
            self.svc.create_user("adm1", "mgomez", "m@x.com", "María Gómez")        # duplicado
        with self.assertRaises(AdminError):
            self.svc.create_user("adm1", "X!", "m@x.com", "n")                      # usuario inválido

    def test_dual_control_happy_path_and_sessions_revoked(self):
        rid = self.svc.request_role_change("adm1", "aud1", AUDITOR, "GRANT", "Ingreso al equipo de auditoría")
        self.assertEqual(self.repo.users["aud1"].roles, [])                          # aún no se aplica
        self.svc.decide_role_request("con1", [CONTRALOR], rid, True, "ok")
        self.assertEqual(self.repo.users["aud1"].roles, [AUDITOR])
        self.assertIn("aud1", self.repo.sessions_revoked)

    def test_requester_target_and_non_approver_cannot_decide(self):
        rid = self.svc.request_role_change("adm1", "aud1", AUDITOR, "GRANT", "Ingreso al equipo de auditoría")
        for actor, roles in (("adm1", [CONTRALOR]), ("aud1", [CONTRALOR])):
            with self.assertRaises(AdminError) as c:
                self.svc.decide_role_request(actor, roles, rid, True)
            self.assertEqual(c.exception.code, "DUAL_CONTROL")
        with self.assertRaises(AdminError) as c:                                     # otro admin sin role:approve
            self.svc.decide_role_request("adm2", [SYS_ADMIN], rid, True)
        self.assertEqual(c.exception.code, "FORBIDDEN")

    def test_nobody_requests_roles_for_self(self):
        with self.assertRaises(AdminError) as c:
            self.svc.request_role_change("adm1", "adm1", CONTRALOR, "GRANT", "Quiero ser contralor también")
        self.assertEqual(c.exception.code, "SELF_CHANGE")

    def test_sod_violation_blocked_at_request_and_at_approval(self):
        self.repo.users["aud1"].roles = [AUDITOR]
        with self.assertRaises(AdminError) as c:
            self.svc.request_role_change("adm1", "aud1", CONTRALOR, "GRANT", "Promoción a contraloría")
        self.assertEqual(c.exception.code, "SOD_VIOLATION")
        # Solicitud válida cuando aún no tenía el rol; luego el estado cambia antes de aprobar
        self.repo.users["aud1"].roles = []
        rid = self.svc.request_role_change("adm1", "aud1", CONTRALOR, "GRANT", "Promoción a contraloría")
        self.repo.users["aud1"].roles = [AUDITOR]                                    # cambió mientras estaba pendiente
        with self.assertRaises(AdminError) as c:
            self.svc.decide_role_request("con1", [CONTRALOR], rid, True)
        self.assertEqual(c.exception.code, "SOD_VIOLATION")
        self.assertEqual(self.repo.users["aud1"].roles, [AUDITOR])                  # no se aplicó

    def test_reason_required_and_duplicates_blocked(self):
        with self.assertRaises(AdminError):
            self.svc.request_role_change("adm1", "aud1", AUDITOR, "GRANT", "corto")
        self.svc.request_role_change("adm1", "aud1", AUDITOR, "GRANT", "Ingreso al equipo de auditoría")
        with self.assertRaises(AdminError) as c:
            self.svc.request_role_change("adm2", "aud1", AUDITOR, "GRANT", "Ingreso al equipo de auditoría")
        self.assertEqual(c.exception.code, "PENDING_EXISTS")

    def test_cannot_remove_last_admin(self):
        self.repo.users["adm2"].is_active = False
        with self.assertRaises(AdminError) as c:
            self.svc.set_active("con1", "adm1", False)
        self.assertEqual(c.exception.code, "LAST_ADMIN")
        with self.assertRaises(AdminError) as c:
            self.svc.request_role_change("con1", "adm1", SYS_ADMIN, "REVOKE", "Retiro del administrador")
        self.assertEqual(c.exception.code, "LAST_ADMIN")

    def test_self_deactivation_and_mfa_reset(self):
        with self.assertRaises(AdminError):
            self.svc.set_active("adm1", "adm1", False)
        with self.assertRaises(AdminError):
            self.svc.reset_mfa("adm1", "adm1")
        self.svc.reset_mfa("adm1", "aud1")
        self.assertIn("aud1", self.repo.mfa_reset)
        self.assertIn("aud1", self.repo.sessions_revoked)

    def test_reject_leaves_roles_untouched(self):
        rid = self.svc.request_role_change("adm1", "aud1", GERENCIA, "GRANT", "Cambio de cargo a gerencia")
        self.svc.decide_role_request("con1", [CONTRALOR], rid, False, "no procede")
        self.assertEqual(self.repo.users["aud1"].roles, [])
        with self.assertRaises(AdminError):
            self.svc.decide_role_request("con1", [CONTRALOR], rid, True)            # ya resuelta


if __name__ == "__main__":
    unittest.main()
