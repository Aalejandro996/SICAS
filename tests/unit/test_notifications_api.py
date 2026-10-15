"""Pruebas HTTP para autenticación y aislamiento de las notificaciones."""
import unittest
from unittest.mock import patch

from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.modules.notifications.api import bp


class NotificationsApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask("notification_api_tests")
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="clave-exclusiva-de-pruebas-notificaciones",
            JWT_ACCESS_TOKEN_EXPIRES=False,
        )
        JWTManager(self.app)
        self.app.register_blueprint(bp, url_prefix="/notifications")
        self.client = self.app.test_client()
        self.user_id = "00000000-0000-0000-0000-000000000001"

    def headers(self, mfa=True):
        with self.app.app_context():
            token = create_access_token(
                identity=self.user_id,
                additional_claims={"mfa": mfa, "perms": []},
            )
        return {"Authorization": f"Bearer {token}"}

    def test_notification_list_requires_authentication(self):
        self.assertEqual(self.client.get("/notifications/").status_code, 401)

    def test_notification_list_requires_completed_mfa(self):
        response = self.client.get("/notifications/", headers=self.headers(mfa=False))
        self.assertEqual(response.status_code, 403)

    def test_list_is_scoped_to_authenticated_user(self):
        with patch("app.modules.notifications.api.service.list_notifications", return_value=[]) as list_mock:
            response = self.client.get(
                "/notifications/?view=unread", headers=self.headers()
            )
        self.assertEqual(response.status_code, 200)
        list_mock.assert_called_once_with(self.user_id, "unread", 100)

    def test_invalid_view_is_rejected(self):
        response = self.client.get(
            "/notifications/?view=other-user", headers=self.headers()
        )
        self.assertEqual(response.status_code, 400)

    def test_mark_read_is_scoped_to_authenticated_user(self):
        notification_id = "00000000-0000-0000-0000-000000000099"
        with patch("app.modules.notifications.api.service.mark_read", return_value=False) as mark_mock:
            response = self.client.post(
                f"/notifications/{notification_id}/read", headers=self.headers()
            )
        self.assertEqual(response.status_code, 404)
        mark_mock.assert_called_once_with(self.user_id, notification_id)

    def test_attend_is_scoped_to_authenticated_user(self):
        notification_id = "00000000-0000-0000-0000-000000000098"
        with patch("app.modules.notifications.api.service.mark_attended", return_value=True) as mark_mock:
            response = self.client.post(
                f"/notifications/{notification_id}/attend", headers=self.headers()
            )
        self.assertEqual(response.status_code, 200)
        mark_mock.assert_called_once_with(self.user_id, notification_id)


if __name__ == "__main__":
    unittest.main()
