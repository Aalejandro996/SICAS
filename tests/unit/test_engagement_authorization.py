import unittest
from unittest.mock import patch

from flask import Flask

from app.modules.engagement import api as engagement_api


class ReportDomainAuthorizationTests(unittest.TestCase):
    REPORT_ID = "00000000-0000-0000-0000-000000000101"
    AUDIT_ID = "00000000-0000-0000-0000-000000000201"

    def fetch_report(self, permissions, audit_domain):
        report = {
            "id": self.REPORT_ID,
            "audit_id": self.AUDIT_ID,
            "kind": "FINAL",
            "status": "SIGNED",
        }
        audit = {
            "id": self.AUDIT_ID,
            "audit_domain": audit_domain,
        }

        app = Flask("engagement-authorization-test")
        with app.app_context():
            with (
                patch.object(
                    engagement_api.repo, "get_report", return_value=report
                ),
                patch.object(
                    engagement_api.repo, "get_audit", return_value=audit
                ),
                patch.object(
                    engagement_api, "perms", return_value=set(permissions)
                ),
                patch.object(
                    engagement_api, "_team_info", return_value=[]
                ),
                patch.object(
                    engagement_api.repo, "is_member", return_value=False
                ),
            ):
                return engagement_api.get_rep(
                    self.REPORT_ID, final_viewer=True
                )

    def assert_denied(self, result):
        report, audit, team, error = result
        self.assertIsNone(report)
        self.assertIsNone(audit)
        self.assertIsNone(team)
        self.assertIsNotNone(error)
        self.assertEqual(error[1], 404)

    def test_financial_user_cannot_read_systems_final_report(self):
        self.assert_denied(
            self.fetch_report(
                {"audit:read_final", "audit:financial_read"},
                "SISTEMAS",
            )
        )

    def test_systems_user_cannot_read_financial_final_report(self):
        self.assert_denied(
            self.fetch_report(
                {"audit:read_final", "audit:systems_read"},
                "FINANCIERA",
            )
        )

    def test_financial_user_can_read_financial_final_report(self):
        report, audit, team, error = self.fetch_report(
            {"audit:read_final", "audit:financial_read"},
            "FINANCIERA",
        )
        self.assertEqual(report["id"], self.REPORT_ID)
        self.assertEqual(audit["audit_domain"], "FINANCIERA")
        self.assertIsNone(error)

    def test_systems_user_can_read_systems_final_report(self):
        report, audit, team, error = self.fetch_report(
            {"audit:read_final", "audit:systems_read"},
            "SISTEMAS",
        )
        self.assertEqual(report["id"], self.REPORT_ID)
        self.assertEqual(audit["audit_domain"], "SISTEMAS")
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
