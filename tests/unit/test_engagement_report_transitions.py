"""Transiciones del informe final: compare-and-set, registro atómico y rechazo de saltos de etapa por API."""
import time
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, g
from flask_jwt_extended import JWTManager, create_access_token

from app.modules.engagement import api as engagement_api
from app.modules.engagement import repositories as repo

REPORT_ID = "00000000-0000-0000-0000-000000000101"
AUDIT_ID = "00000000-0000-0000-0000-000000000201"
AUDITOR = "00000000-0000-0000-0000-000000000001"
JEFE = "00000000-0000-0000-0000-000000000002"
GERENTE = "00000000-0000-0000-0000-000000000003"
CONTRALOR = "00000000-0000-0000-0000-000000000004"
SHA = "a" * 64
OBS_ID = "00000000-0000-0000-0000-000000000501"
SHEET_ID = "00000000-0000-0000-0000-000000000301"
ITEM_ID = "00000000-0000-0000-0000-000000000401"
FOREIGN_ID = "00000000-0000-0000-0000-000000000999"

JEFE_PERMS = ["audit:read", "audit:systems_read", "audit:systems_review", "audit:report_approve_jefe"]
GERENTE_PERMS = ["audit:read_final", "audit:report_approve_gerente", "audit:sign_gerente"]
CONTRALOR_PERMS = ["audit:read", "audit:read_final", "audit:report_approve", "audit:sign_contralor"]
AUDITOR_PERMS = ["audit:read", "audit:systems_read", "audit:systems_manage", "audit:report_submit", "audit:initial"]


class TransitionReportRepositoryTests(unittest.TestCase):
    """repo.transition_report sin base de datos: se inspecciona el SQL y el manejo de la transacción."""

    def call(self, update_row=("id",), **overrides):
        kwargs = dict(
            expected_status="IN_REVIEW", expected_sha256=SHA, status="GERENCIA",
            action="APPROVE_JEFE", actor=JEFE, report_version=1,
            actor_username="jefe", actor_roles=["JEFE_AUDITORIA_SISTEMAS"],
        )
        kwargs.update(overrides)
        statements = []

        def fake_x(sql, **params):
            statements.append((sql, params))
            result = MagicMock()
            result.first.return_value = update_row if sql.startswith("UPDATE") else None
            return result

        db = MagicMock()
        with patch.object(repo, "x", side_effect=fake_x), patch.object(repo, "db", db):
            try:
                repo.transition_report(REPORT_ID, **kwargs)
                raised = None
            except Exception as ex:  # noqa: BLE001
                raised = ex
        return statements, db, raised

    def test_update_is_guarded_by_expected_status_and_content(self):
        statements, db, raised = self.call()
        self.assertIsNone(raised)
        update_sql, params = statements[0]
        self.assertIn("WHERE id = CAST(:i AS uuid) AND status = :expected AND body_sha256 = :sha", update_sql)
        self.assertEqual(params["expected"], "IN_REVIEW")
        self.assertEqual(params["sha"], SHA)
        self.assertEqual(params["s"], "GERENCIA")
        db.session.commit.assert_called_once()
        db.session.rollback.assert_not_called()

    def test_transition_row_is_written_in_the_same_transaction(self):
        statements, db, _ = self.call()
        inserts = [(s, p) for s, p in statements if "report_transitions" in s]
        self.assertEqual(len(inserts), 1)
        params = inserts[0][1]
        self.assertEqual(params["f"], "IN_REVIEW")
        self.assertEqual(params["t"], "GERENCIA")
        self.assertEqual(params["action"], "APPROVE_JEFE")
        self.assertEqual(params["h"], SHA)
        self.assertEqual(params["u"], JEFE)
        self.assertEqual(params["roles"], ["JEFE_AUDITORIA_SISTEMAS"])
        db.session.commit.assert_called_once()

    def test_stale_state_rolls_back_and_writes_nothing_else(self):
        statements, db, raised = self.call(update_row=None)
        self.assertIsInstance(raised, repo.StaleReportState)
        self.assertEqual(len(statements), 1)
        db.session.rollback.assert_called_once()
        db.session.commit.assert_not_called()

    def test_return_comment_and_signed_doc_share_the_transaction(self):
        signed = MagicMock()
        statements, db, raised = self.call(
            status="RETURNED", action="RETURN", comment="Corregir la observación 3",
            comment_kind="DEVOLUCION",
            signed_doc={"role": "GERENTE_CI", "version": 1, "signed": signed, "key": "k"},
        )
        self.assertIsNone(raised)
        tables = [s.split()[2] for s, _ in statements[1:]]
        self.assertEqual(
            tables,
            ["engagement.report_comments", "engagement.signed_documents", "engagement.report_transitions"],
        )
        db.session.commit.assert_called_once()

    def test_failure_after_update_rolls_back_everything(self):
        def fake_x(sql, **params):
            if "report_transitions" in sql:
                raise RuntimeError("fallo de inserción")
            result = MagicMock()
            result.first.return_value = ("id",)
            return result

        db = MagicMock()
        with patch.object(repo, "x", side_effect=fake_x), patch.object(repo, "db", db):
            with self.assertRaises(RuntimeError):
                repo.transition_report(
                    REPORT_ID, expected_status="IN_REVIEW", expected_sha256=SHA, status="GERENCIA",
                    action="APPROVE_JEFE", actor=JEFE, report_version=1,
                )
        db.session.rollback.assert_called_once()
        db.session.commit.assert_not_called()


class ReportTransitionApiTests(unittest.TestCase):
    """Peticiones HTTP directas: el servidor aplica etapa, rol y compare-and-set."""

    has_gerente = True

    def setUp(self):
        self.app = Flask("report_transition_tests")
        self.app.config.update(TESTING=True, JWT_SECRET_KEY="clave-exclusiva-de-pruebas-transiciones-informe")
        JWTManager(self.app)
        self.app.register_blueprint(engagement_api.bp, url_prefix="/audits")

        @self.app.before_request
        def _rid():
            g.request_id = "00000000-0000-0000-0000-0000000000ff"

        self.client = self.app.test_client()
        self.scanned = {JEFE: {"id": "s1", "content": b"png", "sha256": "0" * 64, "full_name": "Jefe de Prueba"}}
        self.report = {
            "id": REPORT_ID, "audit_id": AUDIT_ID, "kind": "FINAL", "version": 1,
            "status": "IN_REVIEW", "body": {}, "body_sha256": SHA, "created_by": AUDITOR,
            "jefe_approved_by": None, "jefe_approved_body_sha256": None,
            "gerente_approved_by": None, "gerente_approved_body_sha256": None,
            "contralor_approved_by": None, "contralor_approved_body_sha256": None,
            "approved_by": None, "approved_body_sha256": None,
        }
        self.audit = {"id": AUDIT_ID, "code": "AUD-SIS-0001", "audit_domain": "SISTEMAS"}
        self.team = [{"user_id": AUDITOR, "name": "Auditor Uno"}]
        self.points = []
        self.reopened = None
        self.observations = [{"id": OBS_ID, "seq": 1, "title": "Gestión de cambios", "audit_id": AUDIT_ID}]
        self.sheets = [{"id": SHEET_ID, "title": "ERP / TI", "items": [{"id": ITEM_ID, "ref": "ERP-01"}]}]

        patches = [
            patch.object(engagement_api.repo, "get_report", side_effect=lambda rid: dict(self.report)),
            patch.object(engagement_api.repo, "get_audit", side_effect=lambda aid: dict(self.audit)),
            patch.object(engagement_api.repo, "is_member", side_effect=lambda aid, uid: uid == AUDITOR),
            patch.object(engagement_api.repo, "signoffs", return_value=[
                {"signer_type": "AUDITOR_INICIALES", "user_id": AUDITOR, "body_sha256": SHA, "display": "AU"},
            ]),
            patch.object(engagement_api.repo, "signed_docs", return_value=[]),
            patch.object(engagement_api.repo, "active_signature", side_effect=lambda uid, kind="COMPLETA": self.scanned.get(uid)),
            patch.object(engagement_api.repo, "review_points", side_effect=lambda rid: list(self.points)),
            patch.object(engagement_api.repo, "worksheets_with_items", side_effect=lambda aid: list(self.sheets)),
            patch.object(engagement_api.repo, "observations", side_effect=lambda aid: list(self.observations)),
            patch.object(engagement_api.repo, "latest_final", side_effect=lambda aid: dict(self.report)),
            patch.object(engagement_api.repo, "reopening", side_effect=lambda rid: self.reopened),
            patch.object(engagement_api.repo, "get_review_point", side_effect=lambda pid: self.points[0] if self.points else None),
            patch.object(engagement_api.repo, "attend_review_point", return_value=True),
            patch.object(engagement_api.repo, "reopen_report"),
            patch.object(engagement_api.repo, "db"),
            patch.object(engagement_api, "_team_info", side_effect=lambda aid: list(self.team)),
            patch.object(engagement_api, "_phase_snapshot", return_value=None),
            patch.object(engagement_api, "log"),
            patch.object(engagement_api, "notify_report_submitted"),
            patch.object(engagement_api, "notify_report_jefe_approved"),
            patch.object(engagement_api, "notify_report_gerencia_omitted"),
            patch.object(engagement_api, "notify_report_returned"),
            patch.object(engagement_api.repo, "gerencia_available", side_effect=lambda: self.has_gerente),
            patch("app.core.audit.audit_service.audit"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.transition = patch.object(engagement_api.repo, "transition_report").start()
        self.addCleanup(patch.stopall)
        self.add_comment = patch.object(engagement_api.repo, "add_comment").start()
        self.stage_change = patch.object(engagement_api.repo, "stage_change").start()

    def headers(self, user, perms, roles=()):
        with self.app.app_context():
            token = create_access_token(
                identity=user,
                additional_claims={
                    "mfa": True, "mfa_at": time.time(), "perms": perms,
                    "roles": list(roles), "username": f"user-{user[-1]}",
                },
            )
        return {"Authorization": f"Bearer {token}"}

    def post(self, path, user, perms, json=None, roles=()):
        return self.client.post(f"/audits/reports/{REPORT_ID}/{path}", headers=self.headers(user, perms, roles), json=json or {})

    # ---------------------------------------------------------------- compare-and-set
    def test_jefe_approval_is_conditioned_on_the_state_it_validated(self):
        response = self.post("approve/jefe", JEFE, JEFE_PERMS, roles=["JEFE_AUDITORIA_SISTEMAS"])
        self.assertEqual(response.status_code, 200, response.get_json())
        kwargs = self.transition.call_args.kwargs
        self.assertEqual(kwargs["expected_status"], "IN_REVIEW")
        self.assertEqual(kwargs["expected_sha256"], SHA)
        self.assertEqual(kwargs["status"], "GERENCIA")
        self.assertEqual(kwargs["action"], "APPROVE_JEFE")
        self.assertEqual(kwargs["actor"], JEFE)
        self.assertEqual(kwargs["actor_roles"], ["JEFE_AUDITORIA_SISTEMAS"])
        self.assertEqual(kwargs["jefe_approved_body_sha256"], SHA)

    def test_without_gerente_the_report_goes_straight_to_contralor(self):
        self.has_gerente = False
        response = self.post("approve/jefe", JEFE, JEFE_PERMS, roles=["JEFE_AUDITORIA_SISTEMAS"])
        self.assertEqual(response.status_code, 200, response.get_json())
        kwargs = self.transition.call_args.kwargs
        self.assertEqual((kwargs["status"], kwargs["gerencia_omitted"]), ("CONTRALOR", True))
        self.assertIn("Sin Gerente", kwargs["comment"])
        engagement_api.notify_report_gerencia_omitted.assert_called_once()
        engagement_api.notify_report_jefe_approved.assert_not_called()

    def test_jefe_without_scanned_signature_cannot_approve(self):
        self.scanned.pop(JEFE)
        response = self.post("approve/jefe", JEFE, JEFE_PERMS, roles=["JEFE_AUDITORIA_SISTEMAS"])
        self.assertEqual(response.status_code, 409)
        self.assertIn("firma escaneada", response.get_json()["error"])
        self.transition.assert_not_called()

    def test_concurrent_change_returns_conflict_without_side_effects(self):
        self.transition.side_effect = repo.StaleReportState("El informe cambió de estado")
        response = self.post("approve/jefe", JEFE, JEFE_PERMS)
        self.assertEqual(response.status_code, 409)
        engagement_api.notify_report_jefe_approved.assert_not_called()

    def test_submit_records_transition_from_current_state(self):
        self.report["status"] = "RETURNED"
        response = self.post("submit", AUDITOR, AUDITOR_PERMS)
        self.assertEqual(response.status_code, 200, response.get_json())
        kwargs = self.transition.call_args.kwargs
        self.assertEqual((kwargs["expected_status"], kwargs["status"], kwargs["action"]), ("RETURNED", "IN_REVIEW", "SUBMIT"))

    def test_return_writes_comment_inside_the_transition(self):
        response = self.post("return", JEFE, JEFE_PERMS, json={"comment": "Falta evidencia del control C-04"})
        self.assertEqual(response.status_code, 200, response.get_json())
        kwargs = self.transition.call_args.kwargs
        self.assertEqual(kwargs["status"], "RETURNED")
        self.assertEqual(kwargs["action"], "RETURN")
        self.assertEqual(kwargs["comment_kind"], "DEVOLUCION")
        self.assertEqual(kwargs["comment"], "Falta evidencia del control C-04")
        self.assertIsNone(kwargs["jefe_approved_by"])
        self.add_comment.assert_not_called()

    def test_return_requires_a_reason(self):
        response = self.post("return", JEFE, JEFE_PERMS, json={"comment": "corto"})
        self.assertEqual(response.status_code, 400)
        self.transition.assert_not_called()

    # ---------------------------------------------------------------- saltos de etapa y actores no autorizados
    def test_gerencia_cannot_act_before_jefe_approval(self):
        response = self.post("return", GERENTE, GERENTE_PERMS, json={"comment": "Intento de devolución anticipada"})
        self.assertEqual(response.status_code, 403)
        response = self.post("sign/gerente", GERENTE, GERENTE_PERMS)
        self.assertEqual(response.status_code, 409)
        self.assertIn("pendiente de Gerencia", response.get_json()["error"])
        self.transition.assert_not_called()

    def test_contralor_cannot_sign_before_gerencia(self):
        self.report.update(status="GERENCIA", jefe_approved_by=JEFE, jefe_approved_body_sha256=SHA)
        response = self.post("sign/contralor", CONTRALOR, CONTRALOR_PERMS)
        self.assertEqual(response.status_code, 409)
        self.transition.assert_not_called()

    def test_auditor_cannot_approve_as_jefe(self):
        response = self.post("approve/jefe", AUDITOR, AUDITOR_PERMS)
        self.assertEqual(response.status_code, 403)
        self.transition.assert_not_called()

    def test_jefe_in_audit_team_cannot_approve(self):
        self.team.append({"user_id": JEFE, "name": "Jefe en equipo"})
        response = self.post("approve/jefe", JEFE, JEFE_PERMS)
        self.assertEqual(response.status_code, 409)
        self.transition.assert_not_called()

    def test_jefe_cannot_approve_twice(self):
        self.report.update(status="GERENCIA", jefe_approved_by=JEFE, jefe_approved_body_sha256=SHA)
        response = self.post("approve/jefe", JEFE, JEFE_PERMS)
        self.assertEqual(response.status_code, 409)
        self.transition.assert_not_called()

    def test_submit_is_rejected_while_in_review(self):
        response = self.post("submit", AUDITOR, AUDITOR_PERMS)
        self.assertEqual(response.status_code, 409)
        self.transition.assert_not_called()

    # ---------------------------------------------------------------- puntos de devolución
    def test_return_records_validated_review_points(self):
        response = self.post("return", JEFE, JEFE_PERMS, json={
            "comment": "Corregir los puntos indicados antes de reenviar",
            "points": [
                {"target_type": "OBSERVATION", "target_id": OBS_ID, "description": "Precisar la condición"},
                {"target_type": "ITEM", "target_id": ITEM_ID, "description": "Falta evidencia del control"},
                {"description": "Revisar la conclusión general"},
            ],
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        points = self.transition.call_args.kwargs["review_points"]
        self.assertEqual([p["target_type"] for p in points], ["OBSERVATION", "ITEM", "GENERAL"])
        self.assertEqual(points[0]["target_label"], "Observación 1: Gestión de cambios")
        self.assertEqual(points[1]["target_label"], "ERP / TI · ERP-01")
        self.assertIsNone(points[2]["target_id"])

    def test_return_rejects_points_from_another_audit(self):
        response = self.post("return", JEFE, JEFE_PERMS, json={
            "comment": "Corregir los puntos indicados antes de reenviar",
            "points": [{"target_type": "OBSERVATION", "target_id": FOREIGN_ID, "description": "Punto ajeno"}],
        })
        self.assertEqual(response.status_code, 400)
        self.transition.assert_not_called()

    def test_resubmit_is_blocked_while_points_are_pending(self):
        self.report["status"] = "RETURNED"
        self.points = [{"id": 7, "report_id": REPORT_ID, "status": "PENDIENTE", "description": "Precisar la condición"}]
        response = self.post("submit", AUDITOR, AUDITOR_PERMS)
        self.assertEqual(response.status_code, 409)
        self.assertIn("sin atender", response.get_json()["error"])
        self.transition.assert_not_called()

    def test_team_attends_point_with_note_and_history_event(self):
        self.report["status"] = "RETURNED"
        self.points = [{"id": 7, "report_id": REPORT_ID, "status": "PENDIENTE", "description": "Precisar la condición"}]
        response = self.client.post("/audits/review-points/7/attend", headers=self.headers(AUDITOR, AUDITOR_PERMS + ["audit:manage"]),
                                    json={"note": "Se reformuló la condición con la evidencia"})
        self.assertEqual(response.status_code, 200, response.get_json())
        event = self.stage_change.call_args.args[0]
        self.assertEqual(event["action"], "REVIEW_POINT_ATTENDED")
        self.assertEqual(event["reason"], "Se reformuló la condición con la evidencia")

    def test_reviewer_cannot_attend_points(self):
        self.report["status"] = "RETURNED"
        self.points = [{"id": 7, "report_id": REPORT_ID, "status": "PENDIENTE", "description": "Precisar la condición"}]
        response = self.client.post("/audits/review-points/7/attend", headers=self.headers(JEFE, JEFE_PERMS + ["audit:manage"]),
                                    json={"note": "Intento del revisor de cerrar el punto"})
        self.assertEqual(response.status_code, 403)
        self.stage_change.assert_not_called()

    # ---------------------------------------------------------------- reapertura tras la firma
    def signed(self):
        self.report.update(status="SIGNED", jefe_approved_by=JEFE, jefe_approved_body_sha256=SHA,
                           gerente_approved_by=GERENTE, gerente_approved_body_sha256=SHA,
                           contralor_approved_by=CONTRALOR, contralor_approved_body_sha256=SHA)
        self.audit["status"] = "IN_PROGRESS"

    def test_contralor_reopens_signed_report_with_reason(self):
        self.signed()
        response = self.post("reopen", CONTRALOR, CONTRALOR_PERMS, json={"reason": "Hallazgo posterior sobre evidencia del control C-04"})
        self.assertEqual(response.status_code, 200, response.get_json())
        engagement_api.repo.reopen_report.assert_called_once()
        self.assertEqual(self.stage_change.call_args.args[0]["action"], "FINAL_REPORT_REOPENED")

    def test_reopen_requires_signed_latest_version_and_reason(self):
        response = self.post("reopen", CONTRALOR, CONTRALOR_PERMS, json={"reason": "Hallazgo posterior sobre evidencia"})
        self.assertEqual(response.status_code, 409)  # aún IN_REVIEW
        self.signed()
        response = self.post("reopen", CONTRALOR, CONTRALOR_PERMS, json={"reason": "corto"})
        self.assertEqual(response.status_code, 400)
        self.reopened = {"reason": "ya reabierto"}
        response = self.post("reopen", CONTRALOR, CONTRALOR_PERMS, json={"reason": "Hallazgo posterior sobre evidencia del control"})
        self.assertEqual(response.status_code, 409)
        engagement_api.repo.reopen_report.assert_not_called()

    def test_only_contralor_can_reopen(self):
        self.signed()
        for user, perms in ((JEFE, JEFE_PERMS), (GERENTE, GERENTE_PERMS), (AUDITOR, AUDITOR_PERMS)):
            response = self.post("reopen", user, perms, json={"reason": "Intento de reapertura no autorizada del informe"})
            self.assertEqual(response.status_code, 403, user)
        engagement_api.repo.reopen_report.assert_not_called()

    def test_reopened_signed_version_unlocks_audit(self):
        self.signed()
        self.assertTrue(engagement_api.final_locked(AUDIT_ID))
        self.reopened = {"reason": "Hallazgo posterior"}
        self.assertFalse(engagement_api.final_locked(AUDIT_ID))

    def test_audit_stays_locked_through_every_review_stage(self):
        for status in ("IN_REVIEW", "GERENCIA", "CONTRALOR", "SIGNED"):
            self.report["status"] = status
            self.assertTrue(engagement_api.final_locked(AUDIT_ID), status)
        for status in ("DRAFT", "RETURNED"):
            self.report["status"] = status
            self.assertFalse(engagement_api.final_locked(AUDIT_ID), status)


if __name__ == "__main__":
    unittest.main()
