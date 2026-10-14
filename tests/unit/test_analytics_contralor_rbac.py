"""Pruebas HTTP de autorización del dashboard de Contraloría."""
import unittest
from unittest.mock import patch

from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token

from app.core.security.rbac import permission_required


class ContralorAuthorizationHttpTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask("contralor_rbac_tests")
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="clave-exclusiva-de-pruebas-no-usar-en-produccion",
            JWT_ACCESS_TOKEN_EXPIRES=False,
        )
        JWTManager(self.app)

        @self.app.get("/test/contralor")
        @permission_required("dashboard:contralor")
        def dashboard():
            return jsonify(ok=True), 200

        @self.app.post("/test/contralor/kpis")
        @permission_required(
            "dashboard:contralor", "kpi:manage", require_all=True
        )
        def create_kpi():
            return jsonify(ok=True), 201

        self.client = self.app.test_client()

    def token(self, perms, mfa=True):
        with self.app.app_context():
            return create_access_token(
                identity="test-user",
                additional_claims={"perms": perms, "mfa": mfa},
            )

    def headers(self, perms, mfa=True):
        return {
            "Authorization": f"Bearer {self.token(perms, mfa)}"
        }

    def test_dashboard_requires_authentication(self):
        response = self.client.get("/test/contralor")
        self.assertEqual(response.status_code, 401)

    def test_dashboard_rejects_user_without_contralor_permission(self):
        with patch("app.core.audit.audit_service.audit"):
            response = self.client.get(
                "/test/contralor",
                headers=self.headers(["dashboard:executive"]),
            )
        self.assertEqual(response.status_code, 403)

    def test_dashboard_requires_mfa(self):
        with patch("app.core.audit.audit_service.audit"):
            response = self.client.get(
                "/test/contralor",
                headers=self.headers(["dashboard:contralor"], mfa=False),
            )
        self.assertEqual(response.status_code, 403)

    def test_kpi_management_requires_both_permissions(self):
        for perms in (
            ["dashboard:contralor"],
            ["kpi:manage"],
            ["dashboard:executive", "kpi:export"],
        ):
            with self.subTest(perms=perms):
                with patch("app.core.audit.audit_service.audit"):
                    response = self.client.post(
                        "/test/contralor/kpis",
                        headers=self.headers(perms),
                        json={},
                    )
                self.assertEqual(response.status_code, 403)

    def test_kpi_management_accepts_both_required_permissions(self):
        response = self.client.post(
            "/test/contralor/kpis",
            headers=self.headers(["dashboard:contralor", "kpi:manage"]),
            json={},
        )
        self.assertEqual(response.status_code, 201)


if __name__ == "__main__":
    unittest.main()
