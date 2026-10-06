import unittest

from app.core.security import permissions as P


class RbacTest(unittest.TestCase):
    def test_no_role_violates_sod_alone(self):
        for r in P.ROLES:
            self.assertEqual(P.find_sod_violations([r]), [], r)

    def test_auditor_plus_contralor_is_rejected(self):
        self.assertTrue(P.find_sod_violations([P.AUDITOR, P.CONTRALOR]))

    def test_sysadmin_has_no_business_data_access(self):
        perms = P.permissions_for_roles([P.SYS_ADMIN])
        for forbidden in ("finding:read", "report:read", "ingestion:read", "auditlog:read", "report:sign"):
            self.assertNotIn(forbidden, perms)

    def test_gerencia_is_read_only(self):
        perms = P.permissions_for_roles([P.GERENCIA])
        self.assertTrue(all(p.split(":")[1] in ("read_approved", "read_summary", "executive", "verify_signature", "export", "read_final", "sign_gerente")
                            for p in perms))

    def test_only_contralor_signs_and_approves(self):
        for perm in ("report:sign", "report:approve"):
            holders = [r for r, ps in P.ROLE_PERMISSIONS.items() if perm in ps]
            self.assertEqual(holders, [P.CONTRALOR])


if __name__ == "__main__":
    unittest.main()
