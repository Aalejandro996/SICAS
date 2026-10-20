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

    def test_gerencia_can_approve_its_stage_without_operational_edit(self):
        perms = P.permissions_for_roles([P.GERENCIA])

        allowed_actions = {
            "read_approved",
            "read_summary",
            "executive",
            "verify_signature",
            "export",
            "read_final",
            "sign_gerente",
            "report_approve_gerente",
        }
        self.assertTrue(
            all(p.split(":")[1] in allowed_actions for p in perms),
            f"Permisos no previstos para Gerencia: {sorted(perms)}",
        )

        # Gerencia aprueba y firma su etapa, pero no administra auditorías
        # ni modifica cédulas o informes operativos.
        self.assertIn("audit:report_approve_gerente", perms)
        self.assertIn("audit:sign_gerente", perms)

        for forbidden in (
            "audit:read",
            "kpi:export",
            "audit:manage",
            "audit:rate",
            "audit:report_draft",
            "audit:report_submit",
            "audit:template_manage",
            "audit:unit_manage",
        ):
            self.assertNotIn(forbidden, perms)
    def test_systems_audit_roles_are_isolated_from_insurance_engine(self):
        forbidden = {
            "ingestion:upload", "ingestion:read",
            "ingestion:review_rejects", "ingestion:cancel",
            "rule:read", "rule:execute",
            "finding:read", "finding:triage", "finding:escalate",
        }
        roles = (P.AUDITOR_SISTEMAS, P.JEFE_AUDITORIA_SISTEMAS)

        for role in roles:
            with self.subTest(role=role):
                perms = P.permissions_for_roles([role])
                self.assertTrue(
                    forbidden.isdisjoint(perms),
                    f"{role} tiene permisos del motor de seguros: "
                    f"{sorted(forbidden & perms)}",
                )

        self.assertIn(
            "audit:systems_execute",
            P.permissions_for_roles([P.AUDITOR_SISTEMAS]),
        )
        self.assertIn(
            "audit:systems_review",
            P.permissions_for_roles([P.JEFE_AUDITORIA_SISTEMAS]),
        )

    def test_only_contralor_signs_and_approves(self):
        for perm in ("report:sign", "report:approve"):
            holders = [r for r, ps in P.ROLE_PERMISSIONS.items() if perm in ps]
            self.assertEqual(holders, [P.CONTRALOR])


if __name__ == "__main__":
    unittest.main()
