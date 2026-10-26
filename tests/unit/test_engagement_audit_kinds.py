"""Auditorías operativas, especiales, administrativas y financieras: escala, hallazgos SUDEASEG y permisos."""
import time
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, g
from flask_jwt_extended import JWTManager, create_access_token

from app.core.security.permissions import ROLE_LABELS, ROLE_PERMISSIONS
from app.modules.engagement import api as engagement_api
from app.modules.engagement import regulatory_rules as rr
from app.modules.engagement import scoring
from app.modules.engagement.templates import AUDIT_KINDS

CATALOG = [
    {"topic": "pagos", "label": "egresos, pagos y cuentas por pagar", "keywords": ["pago", "factura", "proveedor"],
     "criteria": "Manual de Contabilidad (SUDEASEG)", "cause": "c", "effect": "e", "recommendation": "r", "sort_order": 40},
    {"topic": "general", "label": "control interno de la operación", "keywords": [],
     "criteria": "Ley de la Actividad Aseguradora", "cause": "c", "effect": "e", "recommendation": "r", "sort_order": 999},
]


class ThreeLevelScaleTests(unittest.TestCase):
    def test_boundaries(self):
        t = scoring.AUDIT_THRESHOLDS
        self.assertEqual(scoring.rating(33.3, t), "NO_SATISFACTORIA")
        self.assertEqual(scoring.rating(33.31, t), "ACEPTABLE")
        self.assertEqual(scoring.rating(50, t), "ACEPTABLE")
        self.assertEqual(scoring.rating(50.01, t), "EXCELENTE")
        self.assertEqual(scoring.rating(0, t), "NO_SATISFACTORIA")
        self.assertEqual(scoring.rating(None, t), "SIN_CALIFICAR")

    def test_systems_keep_their_scale(self):
        self.assertEqual(scoring.rating(60, scoring.DEFAULT_THRESHOLDS), "ACEPTABLE")
        self.assertEqual(scoring.rating(91, scoring.DEFAULT_THRESHOLDS), "EXCELENTE")
        self.assertEqual(engagement_api.thresholds({"audit_domain": "FINANCIERA"}), scoring.AUDIT_THRESHOLDS)


class AuditKindsTests(unittest.TestCase):
    def test_kinds_and_units(self):
        self.assertEqual(AUDIT_KINDS["OPERATIVA"]["units"], ("SUCURSAL",))
        self.assertEqual(AUDIT_KINDS["ADMINISTRATIVA"]["units"], ("UNIDAD",))
        self.assertEqual(set(AUDIT_KINDS["ESPECIAL"]["units"]), {"SUCURSAL", "UNIDAD"})
        self.assertEqual(AUDIT_KINDS["FINANCIERA"]["kinds"], ("CXP", "CXC"))

    def test_role_names_drop_financiero(self):
        self.assertEqual(ROLE_LABELS["AUDITOR_FINANCIERO"], "Auditor")
        self.assertEqual(ROLE_LABELS["JEFE_AUDITORIA_FINANCIERA"], "Jefe de Auditoría")


class RegulatoryFindingsTests(unittest.TestCase):
    def sheet(self, answers):
        crit = [{"code": "CXP-01", "source_id": "CXP-01", "section": "Soportes y registro",
                 "text": "Verificar que cada cuenta por pagar cuente con factura o documento soporte."},
                {"code": "CXP-02", "source_id": "CXP-02", "section": "Aprobación y pago", "text": "Verificar la orden de pago aprobada."}]
        items = [{"id": f"i{n}", "ref": f"OP-{n}", "results": {"CXP-01": a1, "CXP-02": a2}} for n, (a1, a2) in enumerate(answers)]
        return {"id": "w1", "title": "Cuentas por pagar", "criteria": crit, "items": items}

    def test_failures_grouped_by_topic_with_rate_based_risk(self):
        ws = self.sheet([("NO_CUMPLE", "CUMPLE"), ("NO_CUMPLE", "CUMPLE"), ("CUMPLE", "PARCIAL"), ("CUMPLE", "CUMPLE")])
        out = rr.findings(ws, CATALOG)
        self.assertEqual(len(out), 1)
        o = out[0]
        self.assertEqual(o["topic"], "pagos")
        self.assertEqual(o["risk"], "ALTO")            # CXP-01: 2 de 4 = 50 %
        self.assertEqual(o["controls"], ["CXP-01", "CXP-02"])
        self.assertIn("2 de 4 (50%)", o["condition"])
        self.assertEqual(o["criteria"], "Manual de Contabilidad (SUDEASEG)")
        self.assertEqual(o["rule_key"], "w1:pagos")
        self.assertEqual(set(o["covered_items"]), {"i0", "i1", "i2"})

    def test_no_failures_no_findings_and_low_rate(self):
        self.assertEqual(rr.findings(self.sheet([("CUMPLE", "CUMPLE")] * 3), CATALOG), [])
        ws = self.sheet([("NO_CUMPLE", "CUMPLE")] + [("CUMPLE", "CUMPLE")] * 9)
        self.assertEqual(rr.findings(ws, CATALOG)[0]["risk"], "BAJO")


class JefeEditsAuditDataTests(unittest.TestCase):
    AID = "00000000-0000-0000-0000-000000000201"

    def setUp(self):
        self.app = Flask("jefe_edit_tests")
        self.app.config.update(TESTING=True, JWT_SECRET_KEY="clave-exclusiva-de-pruebas-jefes-sicas-edicion")
        JWTManager(self.app)
        self.app.register_blueprint(engagement_api.bp, url_prefix="/audits")

        @self.app.before_request
        def _rid():
            g.request_id = "00000000-0000-0000-0000-0000000000fc"

        self.client = self.app.test_client()
        self.audit = {"id": self.AID, "audit_domain": "FINANCIERA", "status": "IN_PROGRESS", "phase": "TRABAJO_CAMPO",
                      "objectives": "Revisar cuentas por pagar", "scope": "Pagos del semestre", "modality": "REMOTA"}
        for name, value in dict(get_audit=MagicMock(side_effect=lambda aid: dict(self.audit)), is_member=MagicMock(return_value=False),
                                latest_final=MagicMock(return_value=None), update_audit_data=MagicMock(), stage_change=MagicMock(),
                                db=MagicMock()).items():
            p = patch.object(engagement_api.repo, name, value); p.start(); self.addCleanup(p.stop)
        for p in (patch.object(engagement_api, "log"), patch("app.core.audit.audit_service.audit")):
            p.start(); self.addCleanup(p.stop)

    def put(self, role):
        with self.app.app_context():
            t = create_access_token(identity="00000000-0000-0000-0000-000000000002", additional_claims={
                "mfa": True, "mfa_at": time.time(), "perms": sorted(ROLE_PERMISSIONS[role]), "roles": [role]})
        return self.client.put(f"/audits/{self.AID}", headers={"Authorization": f"Bearer {t}"},
                               json={"scope": "Pagos y retenciones del semestre", "reason": "El Jefe amplía el alcance acordado"})

    def test_jefe_of_domain_can_edit(self):
        r = self.put("JEFE_AUDITORIA_FINANCIERA")
        self.assertEqual(r.status_code, 200, r.get_json())
        engagement_api.repo.update_audit_data.assert_called_once()

    def test_jefe_of_other_domain_cannot(self):
        self.assertIn(self.put("JEFE_AUDITORIA_SISTEMAS").status_code, (403, 404))
        engagement_api.repo.update_audit_data.assert_not_called()

    def test_auditor_outside_team_cannot(self):
        self.assertIn(self.put("AUDITOR_FINANCIERO").status_code, (403, 404))

    def test_locked_audit_cannot_be_edited_by_jefe(self):
        engagement_api.repo.latest_final.return_value = {"id": "r1", "status": "GERENCIA"}
        with patch.object(engagement_api.repo, "reopening", return_value=None):
            self.assertEqual(self.put("JEFE_AUDITORIA_FINANCIERA").status_code, 403)


if __name__ == "__main__":
    unittest.main()


class KeywordBoundaryTests(unittest.TestCase):
    def test_keyword_must_start_a_word(self):
        catalog = CATALOG + [{"topic": "lcft", "label": "lcft", "keywords": ["rif"], "criteria": "x", "cause": "c", "effect": "e",
                              "recommendation": "r", "sort_order": 30}]
        self.assertEqual(rr.topic_for(catalog, "Verificar que el auxiliar concilie")["topic"], "general")
        self.assertEqual(rr.topic_for(catalog, "RIF vigente del proveedor")["topic"], "lcft")
