"""Auditoría de Sistemas en 4 fases: observaciones automáticas, nota por fase y reglas de verificación progresiva."""
import time
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from flask import Flask, g
from flask_jwt_extended import JWTManager, create_access_token

from app.modules.engagement import api as engagement_api
from app.modules.engagement import observation_rules as rules
from app.modules.engagement import phase_documents, scoring
from app.modules.engagement.report_builder import build_pdf

AUDIT_ID = "00000000-0000-0000-0000-000000000201"
AUDITOR = "00000000-0000-0000-0000-000000000001"
CRIT = {"code": "TI010", "text": "¿Existe un procedimiento formal de respaldo y restauración de las bases de datos?",
        "section": "4. Continuidad", "weight": 1, "evaluation_mode": "ERP_TI"}


class ObservationRulesTests(unittest.TestCase):
    def test_supported_or_unanswered_controls_are_not_gaps(self):
        self.assertIsNone(rules.draft(CRIT, {"control": "SI", "documental": "SI", "evidencia": "ACTUALIZADO"}))
        self.assertIsNone(rules.draft(CRIT, {"control": "", "documental": "", "evidencia": ""}))

    def test_gap_produces_all_seven_fields(self):
        o = rules.draft(CRIT, {"control": "Sí", "documental": "NO", "evidencia": "INEXISTENTE"}, "Solo lo hace el DBA")
        for k in ("risk", "title", "condition", "criteria", "cause", "effect", "recommendation"):
            self.assertTrue(o[k], k)
        self.assertEqual(o["domain"], "respaldos")
        self.assertIn("ISO/IEC 27001:2022", o["criteria"])
        self.assertIn("TI010", o["title"])
        self.assertIn("Solo lo hace el DBA", o["condition"])
        self.assertIn("ransomware", o["effect"])
        # alineado con los indicadores: existe sin soporte documental = MEDIO
        self.assertEqual(o["risk"], "MEDIO")
        # en un dominio crítico (respaldos) la evidencia desactualizada sube de BAJO a MEDIO
        self.assertEqual(rules.draft(CRIT, {"control": "SI", "documental": "SI", "evidencia": "DESACTUALIZADO"})["risk"], "MEDIO")

    def test_risk_levels(self):
        plain = {"code": "X1", "text": "¿Se registra el inventario de licencias?", "section": "Licencias", "weight": 1}
        self.assertEqual(rules.draft(plain, {"control": "NO", "documental": "NO", "evidencia": "INEXISTENTE"})["risk"], "ALTO")
        self.assertEqual(rules.draft(plain, {"control": "SI", "documental": "NO", "evidencia": ""})["risk"], "MEDIO")
        self.assertEqual(rules.draft(plain, {"control": "SI", "documental": "SI", "evidencia": "DESACTUALIZADO"})["risk"], "BAJO")
        heavy = dict(plain, weight=3)
        self.assertEqual(rules.draft(heavy, {"control": "SI", "documental": "SI", "evidencia": "DESACTUALIZADO"})["risk"], "MEDIO")

    def test_output_is_reproducible(self):
        r = {"control": "NO", "documental": "NO", "evidencia": "INEXISTENTE"}
        self.assertEqual(rules.draft(CRIT, r), rules.draft(CRIT, r))


class SystemsOverallTests(unittest.TestCase):
    base = {"auto": 40.0, "final": 40.0, "rating": "NO_SATISFACTORIA", "manual_override": False}

    def test_final_is_simple_average_of_three_closed_phases(self):
        closed = {"LEVANTAMIENTO": {"score": 70}, "DOCUMENTACION": {"score": 55}, "PRUEBAS_CAMPO": {"score": 40}}
        out = scoring.systems_overall(self.base, closed, "INFORME")
        self.assertEqual(out["final"], 55.0)
        self.assertEqual(out["rating"], "NECESITA_MEJORAS")
        self.assertEqual(out["final_method"], "PROMEDIO_FASES")
        self.assertEqual([p["score"] for p in out["phase_scores"]], [70.0, 55.0, 40.0])

    def test_before_informe_the_current_phase_score_is_shown(self):
        out = scoring.systems_overall(self.base, {"LEVANTAMIENTO": {"score": 70}}, "DOCUMENTACION")
        self.assertEqual(out["final"], 40.0)
        self.assertEqual([(p["phase"], p["closed"]) for p in out["phase_scores"]],
                         [("LEVANTAMIENTO", True), ("DOCUMENTACION", False), ("PRUEBAS_CAMPO", False)])

    def test_manual_override_prevails(self):
        closed = {"LEVANTAMIENTO": {"score": 70}, "DOCUMENTACION": {"score": 55}, "PRUEBAS_CAMPO": {"score": 40}}
        out = scoring.systems_overall(self.base, closed, "INFORME", manual=80)
        self.assertEqual((out["final"], out["auto"], out["manual_override"]), (80.0, 55.0, True))


class PhaseDocumentsTests(unittest.TestCase):
    def sheets(self):
        items = [
            {"ref": "TI010", "results": {"TI010": {"control": "SI", "documental": "SI", "evidencia": "DESACTUALIZADO"}},
             "phase_results": {"LEVANTAMIENTO": {"results": {"TI010": {"control": "SI", "documental": "SI", "evidencia": "DESACTUALIZADO"}}},
                               "DOCUMENTACION": {"results": {"TI010": {"control": "SI", "documental": "NO", "evidencia": "INEXISTENTE"}}}}},
            {"ref": "TI011", "results": {"TI011": {"control": "SI", "documental": "NO"}}, "phase_results": {}},
        ]
        return [{"kind": "SISTEMAS", "criteria": [CRIT, dict(CRIT, code="TI011")], "items": items}]

    def test_letter_lists_controls_documented_in_levantamiento_whatever_their_state(self):
        controls = phase_documents.documented_controls(self.sheets(), "LEVANTAMIENTO")
        self.assertEqual([(c["ref"], c["evidence"]) for c in controls], [("TI010", "Desactualizada")])
        pdf = phase_documents.documentation_request_pdf(audit={"code": "AUD-1", "unit_name": "TI"}, team=[], controls=controls,
                                                        company="Aseguradora", due=date(2026, 11, 5), today=date(2026, 10, 26))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_field_tests_only_for_controls_documented_in_documentacion(self):
        self.assertEqual(phase_documents.documented_controls(self.sheets(), "DOCUMENTACION"), [])
        pdf = phase_documents.field_tests_pdf(audit={"code": "AUD-1"}, team=[], controls=[], company="Aseguradora", today=date(2026, 10, 26))
        self.assertTrue(pdf.startswith(b"%PDF"))


class ReportWithoutLeaderTests(unittest.TestCase):
    def test_pdf_with_phase_scores_and_team_roles(self):
        body = {"kind": "FINAL", "version": 1, "company": "Aseguradora", "generated_on": "2026-10-26", "audit_code": "AUD-1",
                "file_code": "EXP-1", "title": "Seguridad TI", "unit": {"code": "U", "name": "TI", "kind": "UNIDAD"},
                "modality": "PRESENCIAL", "period": {"from": "2026-10-22", "to": "2026-10-30"}, "objectives": "o", "scope": "s",
                "procedures": "", "contact": {"name": "", "role": ""},
                "team": [{"name": "Ana Pérez", "initials": "AP", "role": "LIDER", "system_role": "Auditor de Sistemas"}],
                "sheets": [], "observations": [], "limitations": [], "adjustments": [], "evidence": [], "conclusion": "c",
                "thresholds": {}, "indicators": {"overall": {}, "worksheets": []},
                "overall": scoring.systems_overall({"auto": 40, "final": 40, "rating": "NO_SATISFACTORIA"},
                                                   {"LEVANTAMIENTO": {"score": 70}, "DOCUMENTACION": {"score": 55},
                                                    "PRUEBAS_CAMPO": {"score": 40}}, "INFORME")}
        pdf = build_pdf(body, {"final": True})
        self.assertTrue(pdf.startswith(b"%PDF"))


class PhaseRulesApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask("systems_phase_tests")
        self.app.config.update(TESTING=True, JWT_SECRET_KEY="clave-exclusiva-de-pruebas-fases-sistemas-sicas")
        JWTManager(self.app)
        self.app.register_blueprint(engagement_api.bp, url_prefix="/audits")

        @self.app.before_request
        def _rid():
            g.request_id = "00000000-0000-0000-0000-0000000000fd"

        self.client = self.app.test_client()
        self.audit = {"id": AUDIT_ID, "audit_domain": "SISTEMAS", "status": "IN_PROGRESS", "phase": "DOCUMENTACION"}
        self.item = {"id": "00000000-0000-0000-0000-000000000401", "worksheet_id": "w1", "ref": "TI010", "results": {},
                     "phase_results": {"LEVANTAMIENTO": {"results": {"TI010": {"control": "SI", "documental": "SI", "evidencia": "ACTUALIZADO"}}},
                                       "DOCUMENTACION": {"results": {"TI010": {"control": "SI", "documental": "NO", "evidencia": "INEXISTENTE"}}}}}
        ws = {"id": "w1", "audit_id": AUDIT_ID, "kind": "SISTEMAS", "criteria": [CRIT], "items": [self.item]}
        for name, value in dict(get_audit=MagicMock(side_effect=lambda aid: dict(self.audit)), is_member=MagicMock(return_value=True),
                                latest_final=MagicMock(return_value=None), get_item=MagicMock(side_effect=lambda iid: dict(self.item)),
                                get_worksheet=MagicMock(return_value=ws), update_item=MagicMock(), stage_change=MagicMock(),
                                db=MagicMock()).items():
            p = patch.object(engagement_api.repo, name, value); p.start(); self.addCleanup(p.stop)
        for p in (patch.object(engagement_api, "log"), patch("app.core.audit.audit_service.audit")):
            p.start(); self.addCleanup(p.stop)

    def put(self, control, doc="SI", payload=None):
        with self.app.app_context():
            t = create_access_token(identity=AUDITOR, additional_claims={"mfa": True, "mfa_at": time.time(),
                                                                         "perms": ["audit:read", "audit:manage", "audit:systems_read"]})
        body = payload if payload is not None else {"control": control, "documental": doc, "evidencia": "ACTUALIZADO"}
        return self.client.put(f"/audits/items/{self.item['id']}", headers={"Authorization": f"Bearer {t}"},
                               json={"results": {"TI010": body}})

    def saved(self):
        return engagement_api.repo.update_item.call_args.args[1]["TI010"]

    def test_documentacion_registers_what_the_unit_delivered(self):
        # La existencia del control se mantiene como en el Levantamiento, aunque se envíe otra.
        self.assertEqual(self.put("NO", payload={"control": "NO", "doc_status": "DESACTUALIZADA", "doc_note": "Política 2023"}).status_code, 200)
        r = self.saved()
        self.assertEqual((r["control"], r["documental"], r["evidencia"], r["doc_status"]), ("SI", "SI", "DESACTUALIZADO", "DESACTUALIZADA"))
        self.assertEqual(self.put("", payload={"doc_status": "TAL VEZ"}).status_code, 400)

    def test_documentacion_only_for_controls_in_the_letter(self):
        self.item["phase_results"]["LEVANTAMIENTO"]["results"]["TI010"]["documental"] = "NO"
        response = self.put("", payload={"doc_status": "ACTUALIZADA"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("carta", response.get_json()["error"])
        engagement_api.repo.update_item.assert_not_called()

    def test_pruebas_without_documentation_needs_justification_and_scores_zero(self):
        self.audit["phase"] = "PRUEBAS_CAMPO"   # al cierre de Documentación la unidad no entregó (soporte NO)
        self.assertEqual(self.put("", payload={"justification": "La unidad no respondió la carta en el plazo."}).status_code, 200)
        r = self.saved()
        self.assertTrue(r["sin_doc"]); self.assertEqual(r["outcome"], "SIN_DOC")
        self.assertEqual(scoring.system_item_score([CRIT], {"TI010": r}), 0.0)

    def test_pruebas_with_documentation_answers_three_questions(self):
        self.audit["phase"] = "PRUEBAS_CAMPO"
        self.item["phase_results"]["DOCUMENTACION"]["results"]["TI010"] = {"control": "SI", "doc_status": "ACTUALIZADA"}
        self.assertEqual(self.put("", payload={"q1": "SI", "q2": "SI", "q3": "NO"}).status_code, 200)
        r = self.saved()
        self.assertEqual((r["outcome"], r["control"], r["documental"], r["evidencia"]), ("PARCIAL", "SI", "SI", "INEXISTENTE"))
        self.assertEqual(scoring.system_item_score([CRIT], {"TI010": r}), 70.0)

    def test_controls_are_closed_in_informe(self):
        self.audit["phase"] = "INFORME"
        self.assertEqual(self.put("SI").status_code, 409)

    def test_systems_audit_cannot_use_financial_phases(self):
        self.assertEqual(engagement_api.phases_for(self.audit), scoring.SYSTEM_PHASES)
        self.assertEqual(engagement_api.phases_for({"audit_domain": "FINANCIERA"}), engagement_api.PHASES)


if __name__ == "__main__":
    unittest.main()
