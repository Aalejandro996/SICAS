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

    def setUp(self):
        self.app = Flask("report_transition_tests")
        self.app.config.update(TESTING=True, JWT_SECRET_KEY="clave-exclusiva-de-pruebas-transiciones-informe")
        JWTManager(self.app)
        self.app.register_blueprint(engagement_api.bp, url_prefix="/audits")

        @self.app.before_request
        def _rid():
            g.request_id = "00000000-0000-0000-0000-0000000000ff"

        self.client = self.app.test_client()
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

        patches = [
            patch.object(engagement_api.repo, "get_report", side_effect=lambda rid: dict(self.report)),
            patch.object(engagement_api.repo, "get_audit", side_effect=lambda aid: dict(self.audit)),
            patch.object(engagement_api.repo, "is_member", side_effect=lambda aid, uid: uid == AUDITOR),
            patch.object(engagement_api.repo, "signoffs", return_value=[
                {"signer_type": "AUDITOR_INICIALES", "user_id": AUDITOR, "body_sha256": SHA, "display": "AU"},
            ]),
            patch.object(engagement_api.repo, "signed_docs", return_value=[]),
            patch.object(engagement_api, "_team_info", side_effect=lambda aid: list(self.team)),
            patch.object(engagement_api, "_phase_snapshot", return_value=None),
            patch.object(engagement_api, "log"),
            patch.object(engagement_api, "notify_report_submitted"),
            patch.object(engagement_api, "notify_report_jefe_approved"),
            patch.object(engagement_api, "notify_report_returned"),
            patch("app.core.audit.audit_service.audit"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.transition = patch.object(engagement_api.repo, "transition_report").start()
        self.addCleanup(patch.stopall)
        self.add_comment = patch.object(engagement_api.repo, "add_comment").start()

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


if __name__ == "__main__":
    unittest.main()
