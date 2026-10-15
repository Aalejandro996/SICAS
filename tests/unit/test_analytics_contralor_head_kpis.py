"""Pruebas de aislamiento por propietario y dominio para KPI de jefaturas."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import UUID

from flask import Blueprint, Flask
from flask_jwt_extended import JWTManager, create_access_token

from app.modules.analytics import contralor_service as service
from app.modules.analytics.contralor_api import register_contralor_routes


FIN_HEAD = "11111111-1111-4111-8111-111111111111"
SYS_HEAD = "22222222-2222-4222-8222-222222222222"
OTHER_HEAD = "33333333-3333-4333-8333-333333333333"
FIN_AUDITOR = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KPI_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def kpi_payload(**overrides):
    data = {
        "name": "Cumplimiento de auditorías",
        "description": "Medición de prueba",
        "metric_code": "AUDITS_TOTAL",
        "target_value": 5,
        "warning_value": 2,
        "direction": "AT_LEAST",
        "periodicity": "MENSUAL",
        "scope_type": "AUDITOR",
        "unit_id": None,
        "auditor_id": FIN_AUDITOR,
    }
    data.update(overrides)
    return data


class HeadKpiHttpAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask("contralor_head_kpi_tests")
        self.app.config.update(
            TESTING=True,
            JWT_SECRET_KEY="clave-exclusiva-de-pruebas-no-usar-en-produccion",
            JWT_ACCESS_TOKEN_EXPIRES=False,
        )
        JWTManager(self.app)
        bp = Blueprint("contralor_head_kpi_test_routes", __name__)
        register_contralor_routes(bp)
        self.app.register_blueprint(bp, url_prefix="/analytics")
        self.client = self.app.test_client()

    def headers(self, perms, identity=FIN_HEAD, mfa=True):
        with self.app.app_context():
            token = create_access_token(
                identity=identity,
                additional_claims={"perms": perms, "mfa": mfa},
            )
        return {"Authorization": f"Bearer {token}"}

    def test_financial_head_lists_only_owned_financial_kpis(self):
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_api.service.list_kpis", return_value=[]
        ) as list_kpis:
            response = self.client.get(
                "/analytics/contralor/kpis/mine?all=1",
                headers=self.headers(["audit:financial_review"], identity=FIN_HEAD),
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(
            list_kpis.call_args.kwargs,
            {"include_inactive": True, "owner_id": FIN_HEAD, "audit_domain": "FINANCIERA"},
        )
        metrics = response.get_json()["metrics"]
        self.assertNotIn("INGESTION_AVG_SECONDS", metrics)
        self.assertNotIn("INGESTION_REJECTION_PCT", metrics)

    def test_systems_head_lists_only_owned_systems_kpis(self):
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_api.service.list_kpis", return_value=[]
        ) as list_kpis:
            response = self.client.get(
                "/analytics/contralor/kpis/mine",
                headers=self.headers(["audit:systems_review"], identity=SYS_HEAD),
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(
            list_kpis.call_args.kwargs,
            {"include_inactive": False, "owner_id": SYS_HEAD, "audit_domain": "SISTEMAS"},
        )

    def test_heads_cannot_use_contralor_global_kpi_list(self):
        with patch("app.core.audit.audit_service.audit"):
            response = self.client.get(
                "/analytics/contralor/kpis",
                headers=self.headers(["audit:financial_review"], identity=FIN_HEAD),
            )
        self.assertEqual(response.status_code, 403)

    def test_two_domain_review_permissions_do_not_create_global_scope(self):
        with patch("app.core.audit.audit_service.audit"):
            response = self.client.get(
                "/analytics/contralor/kpis/mine",
                headers=self.headers(
                    ["audit:financial_review", "audit:systems_review"], identity=FIN_HEAD
                ),
            )
        self.assertEqual(response.status_code, 403)

    def test_financial_head_create_route_passes_server_selected_domain(self):
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_api.service.create_kpi",
            return_value={"id": KPI_ID},
        ) as create_kpi:
            response = self.client.post(
                "/analytics/contralor/kpis/mine",
                headers=self.headers(["audit:financial_review"], identity=FIN_HEAD),
                json=kpi_payload(),
            )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        create_kpi.assert_called_once_with(
            kpi_payload(), FIN_HEAD, audit_domain="FINANCIERA"
        )

    def test_systems_head_create_route_passes_server_selected_domain(self):
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_api.service.create_kpi",
            return_value={"id": KPI_ID},
        ) as create_kpi:
            response = self.client.post(
                "/analytics/contralor/kpis/mine",
                headers=self.headers(["audit:systems_review"], identity=SYS_HEAD),
                json=kpi_payload(),
            )
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        create_kpi.assert_called_once_with(
            kpi_payload(), SYS_HEAD, audit_domain="SISTEMAS"
        )

    def test_financial_head_cannot_create_kpi_for_auditor_outside_domain(self):
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_service._auditor_belongs_to_domain",
            return_value=False,
        ) as belongs:
            response = self.client.post(
                "/analytics/contralor/kpis/mine",
                headers=self.headers(["audit:financial_review"], identity=FIN_HEAD),
                json=kpi_payload(),
            )
        self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertIn("no pertenece", response.get_json()["error"].lower())
        belongs.assert_called_once_with(FIN_AUDITOR, "FINANCIERA")

    def test_financial_head_update_route_passes_owner_and_domain(self):
        changes = {"name": "Meta actualizada"}
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_api.service.update_kpi",
            return_value={"id": KPI_ID},
        ) as update_kpi:
            response = self.client.patch(
                f"/analytics/contralor/kpis/mine/{KPI_ID}",
                headers=self.headers(["audit:financial_review"], identity=FIN_HEAD),
                json=changes,
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        update_kpi.assert_called_once_with(
            KPI_ID, changes, FIN_HEAD, audit_domain="FINANCIERA"
        )

    def test_head_history_route_checks_ownership_before_returning_history(self):
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_api.service.assert_kpi_management_access"
        ) as access, patch(
            "app.modules.analytics.contralor_api.service.get_kpi_measurement_history",
            return_value=[],
        ) as history:
            response = self.client.get(
                f"/analytics/contralor/kpis/mine/{KPI_ID}/history?limit=12",
                headers=self.headers(["audit:systems_review"], identity=SYS_HEAD),
            )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        access.assert_called_once_with(KPI_ID, SYS_HEAD, "SISTEMAS")
        history.assert_called_once_with(KPI_ID, 12)

    def test_head_history_returns_not_found_for_kpi_not_owned_or_not_in_domain(self):
        with patch("app.core.audit.audit_service.audit"), patch(
            "app.modules.analytics.contralor_api.service.assert_kpi_management_access",
            side_effect=LookupError("KPI no encontrado."),
        ), patch(
            "app.modules.analytics.contralor_api.service.get_kpi_measurement_history"
        ) as history:
            response = self.client.get(
                f"/analytics/contralor/kpis/mine/{KPI_ID}/history",
                headers=self.headers(["audit:financial_review"], identity=FIN_HEAD),
            )
        self.assertEqual(response.status_code, 404)
        history.assert_not_called()


class HeadKpiServiceIsolationTests(unittest.TestCase):
    def test_head_scope_rejects_general_kpi(self):
        with self.assertRaisesRegex(ValueError, "alcance de auditor individual"):
            service._validate_kpi(
                kpi_payload(scope_type="GENERAL", auditor_id=None),
                audit_domain="FINANCIERA",
            )

    def test_head_scope_rejects_ingestion_metrics_without_domain(self):
        payload = kpi_payload(metric_code="INGESTION_AVG_SECONDS")
        with patch(
            "app.modules.analytics.contralor_service._auditor_belongs_to_domain",
            return_value=True,
        ) as belongs:
            with self.assertRaisesRegex(ValueError, "no está separada por dominio"):
                service._validate_kpi(payload, audit_domain="FINANCIERA")
        belongs.assert_not_called()

    def test_head_scope_rejects_auditor_from_other_domain(self):
        with patch(
            "app.modules.analytics.contralor_service._auditor_belongs_to_domain",
            return_value=False,
        ):
            with self.assertRaisesRegex(ValueError, "no pertenece al dominio"):
                service._validate_kpi(kpi_payload(), audit_domain="FINANCIERA")

    def test_head_scope_accepts_auditor_after_domain_validation(self):
        with patch(
            "app.modules.analytics.contralor_service._auditor_belongs_to_domain",
            return_value=True,
        ) as belongs:
            result = service._validate_kpi(kpi_payload(), audit_domain="FINANCIERA")
        belongs.assert_called_once_with(FIN_AUDITOR, "FINANCIERA")
        self.assertEqual(result["scope_type"], "AUDITOR")
        self.assertEqual(result["auditor_id"], FIN_AUDITOR)
        self.assertIsNone(result["unit_id"])

    def _fake_kpi_db(self, owner=FIN_HEAD, auditor=FIN_AUDITOR):
        current = {
            "id": UUID(KPI_ID),
            "created_by": UUID(owner),
            "scope_type": "AUDITOR",
            "metric_code": "AUDITS_TOTAL",
            "auditor_id": UUID(auditor),
        }
        result = MagicMock()
        result.mappings.return_value.first.return_value = current
        fake_db = SimpleNamespace(session=SimpleNamespace(execute=MagicMock(return_value=result)))
        return fake_db, current

    def test_service_denies_kpi_owned_by_another_head(self):
        fake_db, _ = self._fake_kpi_db(owner=OTHER_HEAD)
        with patch("app.modules.analytics.contralor_service.db", fake_db), patch(
            "app.modules.analytics.contralor_service._auditor_belongs_to_domain",
            return_value=True,
        ) as belongs:
            with self.assertRaises(LookupError):
                service.assert_kpi_management_access(KPI_ID, FIN_HEAD, "FINANCIERA")
        belongs.assert_not_called()

    def test_service_denies_kpi_if_auditor_is_not_in_requested_domain(self):
        fake_db, _ = self._fake_kpi_db(owner=FIN_HEAD)
        with patch("app.modules.analytics.contralor_service.db", fake_db), patch(
            "app.modules.analytics.contralor_service._auditor_belongs_to_domain",
            return_value=False,
        ) as belongs:
            with self.assertRaises(LookupError):
                service.assert_kpi_management_access(KPI_ID, FIN_HEAD, "SISTEMAS")
        belongs.assert_called_once_with(FIN_AUDITOR, "SISTEMAS")

    def test_service_accepts_only_matching_owner_and_domain(self):
        fake_db, current = self._fake_kpi_db(owner=FIN_HEAD)
        with patch("app.modules.analytics.contralor_service.db", fake_db), patch(
            "app.modules.analytics.contralor_service._auditor_belongs_to_domain",
            return_value=True,
        ):
            result = service.assert_kpi_management_access(KPI_ID, FIN_HEAD, "FINANCIERA")
        self.assertEqual(result["id"], current["id"])
        self.assertEqual(result["created_by"], UUID(FIN_HEAD))

    def test_kpi_list_sql_filters_both_owner_and_domain(self):
        with patch(
            "app.modules.analytics.contralor_service._mappings", return_value=[]
        ) as mappings:
            result = service.list_kpis(
                include_inactive=True, owner_id=FIN_HEAD, audit_domain="FINANCIERA"
            )
        self.assertEqual(result, [])
        sql, params = mappings.call_args.args
        self.assertIn("k.created_by = CAST(:owner_id AS uuid)", sql)
        self.assertIn("k.scope_type = 'AUDITOR'", sql)
        self.assertIn("upper(coalesce(ka.audit_domain,''))=CAST(:audit_domain AS text)", sql)
        self.assertIn("k.metric_code NOT IN ('INGESTION_AVG_SECONDS','INGESTION_REJECTION_PCT')", sql)
        self.assertEqual(params["owner_id"], FIN_HEAD)
        self.assertEqual(params["audit_domain"], "FINANCIERA")


if __name__ == "__main__":
    unittest.main()
