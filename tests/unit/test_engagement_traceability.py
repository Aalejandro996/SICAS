"""Cuadro comparativo, variaciones entre fases, trazabilidad del informe y reglas de edición."""
import time
import unittest
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from flask import Flask, g
from flask_jwt_extended import JWTManager, create_access_token

from app.modules.engagement import api as engagement_api
from app.modules.engagement import assemble, scoring, score_snapshots
from app.modules.engagement.report_builder import build_pdf

AUDIT_ID = "00000000-0000-0000-0000-000000000201"
AUDITOR = "00000000-0000-0000-0000-000000000001"
SYS_CRITERIA = [{"code": "C1", "evaluation_mode": "ERP_TI", "weight": 1}, {"code": "C2", "evaluation_mode": "ERP_TI", "weight": 1}]


def sys_item(code, control, doc="SI", evidence="ACTUALIZADO", manual=None, iid=None):
    return {"id": iid or f"id-{code}", "ref": code, "results": {code: {"control": control, "documental": doc, "evidencia": evidence}},
            "manual_score": manual, "manual_reason": "Ajuste justificado por evidencia" if manual is not None else None,
            "observation": None, "info_exception": None}


class ComparisonTests(unittest.TestCase):
    def test_reference_is_100_and_satisfactorio_threshold(self):
        ws = {"id": "w1", "title": "ERP / TI", "kind": "SISTEMAS", "criteria": SYS_CRITERIA, "manual_score": None,
              "items": [sys_item("C1", "SI"), sys_item("C2", "NO")]}
        overall = scoring.audit_summary([scoring.worksheet_summary(ws["criteria"], ws["items"])])
        cmp_ = scoring.comparison([ws], overall, {"satisfactorio": 70})
        row = cmp_["worksheets"][0]
        self.assertEqual(row["reference"]["expected_score"], 100.0)
        self.assertEqual(row["reference"]["acceptance_threshold"], 70.0)
        self.assertEqual(row["reference"]["items"], 2)
        self.assertEqual(row["result"]["affirmative"], 1)
        self.assertEqual(row["result"]["answered"], 2)
        # SI con documento y evidencia = 100, NO = 0 -> 50
        self.assertEqual(row["result"]["score"], 50.0)
        self.assertEqual(row["differences"]["vs_expected"], -50.0)
        self.assertEqual(row["differences"]["vs_threshold"], -20.0)
        self.assertFalse(row["differences"]["meets_threshold"])
        self.assertEqual(cmp_["overall"]["result"]["score"], overall["final"])

    def test_generic_counts_cumple_as_affirmative_and_excludes_no_aplica(self):
        criteria = [{"code": "A", "weight": 1}, {"code": "B", "weight": 1}]
        ws = {"id": "w", "title": "Suscripción", "kind": "SUSCRIPCION", "criteria": criteria, "manual_score": None,
              "items": [{"results": {"A": "CUMPLE", "B": "NO_APLICA"}}, {"results": {"A": "NO_CUMPLE"}}]}
        overall = scoring.audit_summary([scoring.worksheet_summary(criteria, ws["items"])])
        res = scoring.comparison([ws], overall)["worksheets"][0]["result"]
        self.assertEqual((res["affirmative"], res["answered"], res["not_applicable"], res["pending"]), (1, 2, 1, 1))


class SystemsWithoutParcialTests(unittest.TestCase):
    def test_parcial_does_not_score_and_stays_pending(self):
        self.assertIsNone(scoring.system_item_score(SYS_CRITERIA[:1], {"C1": {"control": "PARCIAL"}}))
        stats = scoring.system_statistics(SYS_CRITERIA, [sys_item("C1", "PARCIAL"), sys_item("C2", "SI")])
        self.assertEqual(stats["respondidas"], 1)
        self.assertEqual(stats["pendientes"], 1)

    def test_questionnaire_import_does_not_accept_parcial(self):
        from app.modules.engagement.system_questionnaire import _control
        self.assertEqual(_control("Parcialmente"), "")
        self.assertEqual(_control("Sí"), "SI")


class SnapshotVariationTests(unittest.TestCase):
    def card(self, controls, manual=None, evidence=(), reason=None):
        ws = {"id": "w1", "title": "ERP / TI", "kind": "SISTEMAS", "criteria": SYS_CRITERIA, "manual_score": None,
              "template_version": 3,
              "items": [sys_item("C1", controls[0], manual=manual, iid="i1"), sys_item("C2", controls[1], iid="i2")]}
        return score_snapshots.build_scorecard({"code": "A", "phase": "TRABAJO_CAMPO"}, [ws], scoring.DEFAULT_THRESHOLDS,
                                               evidence=list(evidence), reason=reason)

    def test_scorecard_keeps_rule_version_template_evidence_and_reason(self):
        card = self.card(("SI", "SI"), evidence=[{"id": "e1", "filename": "acta.pdf", "sha256": "f" * 64}], reason="Cierre de campo")
        self.assertEqual(card["rule_version"], scoring.RULE_VERSION)
        self.assertEqual(card["worksheets"][0]["template_version"], 3)
        self.assertEqual(card["evidence"][0]["filename"], "acta.pdf")
        self.assertEqual(card["reason"], "Cierre de campo")

    def test_variation_reports_delta_items_and_new_evidence(self):
        first = self.card(("SI", "SI"))
        second = self.card(("NO", "SI"), evidence=[{"id": "e1", "filename": "prueba.xlsx", "sha256": "e" * 64}])
        var = score_snapshots.compare(first, second)
        self.assertEqual(var["overall_delta"], -50.0)
        self.assertEqual([(i["ref"], i["before"], i["after"]) for i in var["items"]], [("C1", 100.0, 0.0)])
        self.assertEqual(var["evidence_added"][0]["filename"], "prueba.xlsx")
        self.assertTrue(var["rating_changed"])
        self.assertIsNone(score_snapshots.compare(None, first)["overall_delta"])


class FinalReportTraceTests(unittest.TestCase):
    def body(self):
        ws = {"id": "w1", "kind": "SUSCRIPCION", "line": "AUTO", "title": "x", "criteria": [{"code": "A", "weight": 1}],
              "manual_score": None, "items": [{"ref": "P-1", "results": {"A": "CUMPLE"}, "manual_score": None}]}
        obs = [{"id": "o1", "seq": 1, "title": "Cambios", "condition": "Sin manual actualizado", "risk": "ALTO"}]
        at = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        history = {
            "snapshots": [{"phase": "TRABAJO_CAMPO", "trigger_action": "PHASE_CHANGE", "captured_at": at, "captured_username": "aud",
                           "scorecard": {"overall": {"final": 70.0, "rating": "SATISFACTORIO"}, "reason": "Cierre", "rule_version": "r1"},
                           "variation": {"overall_delta": None, "items": [], "evidence_added": []}},
                          {"phase": "INFORME", "trigger_action": "FINAL_REPORT_SUBMITTED", "captured_at": at, "captured_username": "aud",
                           "scorecard": {"overall": {"final": 55.0, "rating": "NECESITA_MEJORAS"}, "rule_version": "r1"},
                           "variation": {"overall_delta": -15.0, "items": [{"sheet": "x", "ref": "P-1", "before": 100, "after": 0,
                                                                            "delta": -100, "manual_reason": None, "observation": "Falta firma"}],
                                         "evidence_added": [{"filename": "acta.pdf", "sha256": "a" * 64}]}}],
            "observation_revisions": [
                {"observation_id": "o1", "revision": 1, "data": {"title": "Cambio", "condition": "Original", "risk": "MEDIO"}, "created_at": at},
                {"observation_id": "o1", "revision": 2, "data": {}, "changed_fields": ["risk"], "reason": "Se elevó el riesgo por la prueba",
                 "created_at": at, "username": "aud"}],
            "transitions": [{"id": 1, "kind": "FINAL", "action": "RETURN", "report_version": 1, "from_status": "IN_REVIEW",
                             "to_status": "RETURNED", "actor_username": "jefe", "comment": "Corregir riesgo", "created_at": at}],
            "review_points": [{"transition_id": 1, "target_label": "Observación 1", "description": "Riesgo", "status": "ATENDIDO",
                               "attended_note": "Se elevó a ALTO"}],
            "reopenings": [],
        }
        return assemble.assemble(kind="FINAL", audit={"code": "AUD-1", "modality": "REMOTA", "objectives": "o", "scope": "s"},
                                 file={"code": "F", "title": "T", "period_from": "2026-01-01", "period_to": "2026-06-30"},
                                 unit={"code": "U", "name": "Unidad", "kind": "UNIDAD"}, team=[{"name": "Ana Pérez", "initials": "AP", "role": "LIDER"}],
                                 worksheets=[ws], observations=obs, evidence=[{"filename": "acta.pdf", "sha256": "a" * 64}],
                                 thresholds=scoring.DEFAULT_THRESHOLDS, company="SICAS", version=2, today=date(2026, 10, 25),
                                 history=history, revision=3)

    def test_body_explains_score_evolution_changes_and_decisions(self):
        body = self.body()
        self.assertEqual(body["revision"], 3)
        self.assertEqual([h["score"] for h in body["score_history"]], [70.0, 55.0])
        self.assertEqual(body["score_history"][1]["delta"], -15.0)
        self.assertEqual(body["score_history"][1]["changed_items"][0]["reason"], "Falta firma")
        self.assertEqual(body["score_history"][1]["evidence_added"][0]["n"], 1)
        self.assertEqual(body["observation_changes"][0]["original"]["condition"], "Original")
        self.assertEqual(body["observation_changes"][0]["changes"][0]["reason"], "Se elevó el riesgo por la prueba")
        self.assertEqual(body["review_history"][0]["points"][0]["status"], "ATENDIDO")
        self.assertIn("comparison", body)

    def test_pdf_renders_trace_sections(self):
        pdf = build_pdf(self.body(), {"final": True, "transitions": [], "body_sha256": "b" * 64})
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 3000)


class EditRulesApiTests(unittest.TestCase):
    """Reglas de edición aplicadas por la API (motivo obligatorio, SI/NO, vínculo de evidencia)."""

    def setUp(self):
        self.app = Flask("traceability_tests")
        self.app.config.update(TESTING=True, JWT_SECRET_KEY="clave-exclusiva-de-pruebas-trazabilidad-informe")
        JWTManager(self.app)
        self.app.register_blueprint(engagement_api.bp, url_prefix="/audits")

        @self.app.before_request
        def _rid():
            g.request_id = "00000000-0000-0000-0000-0000000000fe"

        self.client = self.app.test_client()
        self.audit = {"id": AUDIT_ID, "audit_domain": "SISTEMAS", "status": "IN_PROGRESS", "phase": "TRABAJO_CAMPO"}
        self.obs = {"id": "00000000-0000-0000-0000-000000000501", "audit_id": AUDIT_ID, "seq": 1, "title": "Gestión de cambios",
                    "condition": "No existe manual vigente", "risk": "ALTO"}
        for target, kw in [
            (engagement_api.repo, dict(get_audit=MagicMock(return_value=self.audit), is_member=MagicMock(return_value=True),
                                       latest_final=MagicMock(return_value=None), get_observation=MagicMock(return_value=self.obs),
                                       update_observation=MagicMock(), stage_change=MagicMock(), get_item=MagicMock(return_value=None),
                                       update_item=MagicMock(), db=MagicMock())),
            (engagement_api, dict(log=MagicMock())),
        ]:
            for name, value in kw.items():
                p = patch.object(target, name, value)
                p.start()
                self.addCleanup(p.stop)
        p = patch("app.core.audit.audit_service.audit")
        p.start()
        self.addCleanup(p.stop)

    def headers(self):
        with self.app.app_context():
            token = create_access_token(identity=AUDITOR, additional_claims={
                "mfa": True, "mfa_at": time.time(), "perms": ["audit:read", "audit:manage", "audit:systems_read"], "roles": ["AUDITOR_SISTEMAS"]})
        return {"Authorization": f"Bearer {token}"}

    def put_obs(self, json):
        return self.client.put(f"/audits/observations/{self.obs['id']}", headers=self.headers(), json=json)

    def test_finding_change_requires_reason(self):
        response = self.put_obs({"risk": "MEDIO"})
        self.assertEqual(response.status_code, 400)
        engagement_api.repo.update_observation.assert_not_called()
        engagement_api.repo.stage_change.assert_not_called()

    def test_finding_change_records_before_after_and_reason(self):
        response = self.put_obs({"risk": "MEDIO", "reason": "La prueba de campo redujo el impacto"})
        self.assertEqual(response.status_code, 200, response.get_json())
        event = engagement_api.repo.stage_change.call_args.args[0]
        self.assertEqual(event["changes"], {"risk": {"before": "ALTO", "after": "MEDIO"}})
        self.assertEqual(event["reason"], "La prueba de campo redujo el impacto")
        args = engagement_api.repo.update_observation.call_args.args
        self.assertEqual(args[2:4], (AUDITOR, "La prueba de campo redujo el impacto"))

    def test_unit_response_gets_default_reason(self):
        response = self.put_obs({"unit_decision": "ACEPTA"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn("respuesta de la unidad", engagement_api.repo.stage_change.call_args.args[0]["reason"])

    def test_systems_item_rejects_parcial(self):
        ws = {"id": "w1", "audit_id": AUDIT_ID, "criteria": SYS_CRITERIA, "items": []}
        item = {"id": "00000000-0000-0000-0000-000000000401", "worksheet_id": "w1", "ref": "C1", "results": {}}
        with patch.object(engagement_api.repo, "get_item", return_value=item), \
             patch.object(engagement_api.repo, "get_worksheet", return_value=ws):
            response = self.client.put(f"/audits/items/{item['id']}", headers=self.headers(),
                                       json={"results": {"C1": {"control": "PARCIAL", "documental": "SI", "evidencia": "ACTUALIZADO"}}})
        self.assertEqual(response.status_code, 400)
        self.assertIn("SI o NO", response.get_json()["error"])
        engagement_api.repo.update_item.assert_not_called()

    def test_evidence_cannot_link_foreign_observation(self):
        foreign = dict(self.obs, audit_id="00000000-0000-0000-0000-000000000999")
        with patch.object(engagement_api.repo, "get_observation", return_value=foreign), \
             patch.object(engagement_api.evidence_rules, "check", return_value=("acta.pdf", "application/pdf")), \
             patch.object(engagement_api.storage, "put") as put:
            response = self.client.post(f"/audits/{AUDIT_ID}/evidence", headers=self.headers(),
                                        data={"observation_id": foreign["id"], "file": (__import__("io").BytesIO(b"%PDF-1.4"), "acta.pdf")})
        self.assertEqual(response.status_code, 400)
        put.assert_not_called()


if __name__ == "__main__":
    unittest.main()
