"""Herramientas del Administrador: política de seguridad, catálogos con doble control y acciones con doble verificación."""
import unittest

from app.core.security.permissions import CONTRALOR, ROLE_PERMISSIONS, SOD_CONFLICTS, SYS_ADMIN
from app.core.security.policy import DEFAULTS, PolicyError, defaults, validate
from app.modules.rules_admin.service import RuleAdminError, RulesAdminService
from tests.unit.test_continuity_and_admin import FakeRulesRepo


class SecurityPolicyTest(unittest.TestCase):
    def test_valid_and_invalid_values(self):
        self.assertEqual(validate({"max_failed_logins": 4, "password_max_age_days": 90}), {"max_failed_logins": 4, "password_max_age_days": 90})
        for bad in ({"max_failed_logins": 1}, {"session_hours": 24}, {"password_max_age_days": 10}, {"otra": 1}, {"lockout_minutes": "30"}, {"step_up_seconds": True}):
            with self.assertRaises(PolicyError):
                validate(bad)

    def test_defaults_match_current_configuration(self):
        cfg = {"MAX_FAILED_LOGINS": 5, "LOCKOUT_MINUTES": 30, "STEP_UP_MAX_AGE_SECONDS": 300}
        self.assertEqual(defaults(cfg), {"max_failed_logins": 5, "lockout_minutes": 30, "step_up_seconds": 300,
                                         "session_hours": 8, "password_max_age_days": 0})
        self.assertEqual(defaults({}), DEFAULTS)


class CatalogProposalTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRulesRepo()
        self.svc = RulesAdminService(self.repo, lambda *a, **k: None, lambda: "c1", lambda code: None)

    def test_new_unit_and_code_validation(self):
        rid = self.svc.propose("adm", "UNIDAD", "SUC-MARACAY", {"name": "Sucursal Maracay", "kind": "SUCURSAL"}, "Apertura de la sucursal")
        self.svc.decide("con", {"rule:configure"}, rid, True)
        self.assertEqual(self.repo.rows[("UNIDAD", "SUC-MARACAY")]["audit_domain"], "GENERAL")
        for key, payload in (("suc minúscula", {"name": "X", "kind": "SUCURSAL"}), ("SUC-X", {"name": "Sucursal X", "kind": "OFICINA"})):
            with self.assertRaises(RuleAdminError):
                self.svc.propose("adm", "UNIDAD", key, payload, "Motivo suficiente")
        rid = self.svc.propose("adm", "CODIFICACION", "COMPANY:NUEVA", {"label": "Nueva Empresa, C.A."}, "Empresa incorporada al grupo")
        self.svc.decide("con", {"rule:configure"}, rid, True)
        with self.assertRaises(RuleAdminError):
            self.svc.propose("adm", "CODIFICACION", "OTRO:X", {"label": "X"}, "Catálogo inexistente")


class TwoStepVerificationTest(unittest.TestCase):
    def test_admin_requests_and_contralor_approves(self):
        for perm in ("audit:annul_request", "backup:restore", "param:update", "session:revoke", "rule:propose"):
            self.assertIn(perm, ROLE_PERMISSIONS[SYS_ADMIN])
        for perm in ("audit:annul_approve", "backup:restore_approve", "admin:action_approve", "rule:configure"):
            self.assertIn(perm, ROLE_PERMISSIONS[CONTRALOR])
            self.assertNotIn(perm, ROLE_PERMISSIONS[SYS_ADMIN])
        pairs = {(a, b) for a, b, _ in SOD_CONFLICTS}
        self.assertTrue({("audit:annul_request", "audit:annul_approve"), ("backup:restore", "backup:restore_approve"),
                         ("param:update", "admin:action_approve")} <= pairs)

    def test_action_validators(self):
        from app.modules.admin import tools
        self.assertEqual(set(tools.ACTIONS), set(tools.ACTION_PERMS))
        payload, summary = tools._v_policy({"value": {"session_hours": 6}})
        self.assertEqual(payload, {"value": {"session_hours": 6}})
        with self.assertRaises(ValueError):
            tools._v_policy({"value": {"session_hours": 48}})
        with self.assertRaises(ValueError):
            tools._v_smtp({"to": "no-es-correo"})
        with self.assertRaises(ValueError):
            tools._v_review({"inactive_days": 5})


if __name__ == "__main__":
    unittest.main()
