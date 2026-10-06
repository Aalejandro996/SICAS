import unittest
from datetime import date

from app.modules.engagement import workflow as wf
from app.modules.engagement.report_builder import SIG_BOX_CONTRALOR, SIG_BOX_GERENTE, body_hash, build_body, build_pdf, initials_of


def sample_body(kind="FINAL"):
    overall = {"auto": 78.5, "final": 78.5, "manual_override": False, "rating": "NECESITA_MEJORAS", "items": 40, "exceptions": 2}
    obs = [{"n": 1, "title": "Falta peritaje firmado", "condition": "En 8 de 20 siniestros no consta peritaje.", "criteria": "Manual de siniestros 4.2",
            "cause": "Sin control", "effect": "Pagos sin soporte", "recommendation": "Exigir peritaje", "risk": "ALTO",
            "unit_decision": "ACEPTA", "unit_response": "De acuerdo", "pac_action": "Checklist obligatorio", "pac_owner": "Gerente", "pac_due": "2026-11-30"},
           {"n": 2, "title": "Archivo incompleto <&>", "condition": "Faltan cédulas.", "risk": "MEDIO"}]
    return build_body(kind=kind, audit={"code": "AUD-2026-0001", "modality": "PRESENCIAL", "objectives": "Evaluar la suscripción y los reclamos.",
                                        "scope": "Pólizas y siniestros de enero a septiembre de 2026.", "procedures": "Muestreo aleatorio.",
                                        "contact_name": "Luis Pérez", "contact_role": "Gerente de Sucursal"},
                      file={"code": "EXP-2026-0001", "title": "Auditoría Sucursal Centro", "period_from": date(2026, 1, 1), "period_to": date(2026, 9, 30)},
                      unit={"code": "SUC01", "name": "Sucursal Centro", "kind": "SUCURSAL"},
                      team=[{"name": "Ana María Gómez Ruiz", "initials": "AG", "role": "LIDER"}, {"name": "Pedro Rojas", "initials": "PR", "role": "AUDITOR"}],
                      sheets=[{"title": "Reclamo — Auto", "kind": "RECLAMO", "line": "AUTO", "items": 20, "scored": 18, "exceptions": 2, "auto": 78.5, "final": 78.5, "manual_override": False, "rating": "NECESITA_MEJORAS"}],
                      overall=overall, observations=obs, limitations=[{"sheet": "Reclamo — Auto", "ref": "SIN-12", "detail": "No entregaron el expediente"}],
                      adjustments=[{"sheet": "Reclamo — Auto", "ref": "SIN-5", "auto": 40.0, "final": 70.0, "reason": "Subsanado durante la visita"}],
                      evidence=[{"n": 1, "filename": "peritaje.pdf", "description": "Peritaje SIN-5", "sha256": "ab" * 32}],
                      company="Aseguradora Ejemplo", version=1, today=date(2026, 10, 2), thresholds={"satisfactorio": 85, "mejora": 70})


class BuilderTest(unittest.TestCase):
    def test_initials(self):
        self.assertEqual(initials_of("María Eugenia Pérez Gómez"), "MP")      # nombre + primer apellido
        self.assertEqual(initials_of("Ana Gómez"), "AG"); self.assertEqual(initials_of("Pedro"), "P"); self.assertEqual(initials_of(""), "??")

    def test_auto_conclusion_mentions_key_facts(self):
        c = sample_body()["conclusion"]
        for frag in ("78.5%", "necesita mejoras", "2 observaciones", "1 de riesgo alto", "2 excepciones", "PAC"):
            self.assertIn(frag, c)
        self.assertIn("PRELIMINAR", sample_body("PREVIO")["conclusion"])

    def test_custom_conclusion_is_kept(self):
        b = build_body(**{**{k: v for k, v in zip(["kind"], ["FINAL"])}, "audit": {"code": "A", "modality": "REMOTA", "objectives": "o", "scope": "s"},
                          "file": {"code": "E", "title": "t", "period_from": "2026-01-01", "period_to": "2026-02-01"}, "unit": {"code": "U", "name": "N", "kind": "UNIDAD"},
                          "team": [], "sheets": [], "overall": {"auto": None, "final": None, "manual_override": False, "rating": "SIN_CALIFICAR", "items": 0, "exceptions": 0},
                          "observations": [], "limitations": [], "adjustments": [], "evidence": [], "company": "C", "version": 1, "today": date(2026, 1, 1),
                          "conclusion": "Texto del auditor"})
        self.assertEqual(b["conclusion"], "Texto del auditor"); self.assertTrue(b["conclusion_custom"])

    def test_body_hash_is_stable_and_sensitive(self):
        a, b = sample_body(), sample_body()
        self.assertEqual(body_hash(a), body_hash(b))
        b["observations"][0]["risk"] = "BAJO"
        self.assertNotEqual(body_hash(a), body_hash(b))

    def test_pdf_generation_draft_and_final(self):
        draft = build_pdf(sample_body(), {"status": "DRAFT", "initials": {"Ana María Gómez Ruiz": "AG"}})
        final = build_pdf(sample_body(), {"final": True, "signed": {"CONTRALOR": "Contralor X", "GERENTE_CI": "Gerente Y"},
                                          "collaborator": {"name": "Luis Pérez", "role": "Gerente"}})
        for pdf in (draft, final):
            self.assertTrue(pdf.startswith(b"%PDF")); self.assertGreater(len(pdf), 4000)
        self.assertNotEqual(draft, final)
        self.assertTrue(build_pdf(sample_body("PREVIO")).startswith(b"%PDF"))

    def test_signature_boxes_fit_in_page_and_do_not_overlap(self):
        for x1, y1, x2, y2 in (SIG_BOX_CONTRALOR, SIG_BOX_GERENTE):
            self.assertTrue(0 < x1 < x2 < 612 and 0 < y1 < y2 < 792)
        self.assertLess(SIG_BOX_CONTRALOR[2], SIG_BOX_GERENTE[0])


class WorkflowTest(unittest.TestCase):
    def st(self, **kw):
        base = dict(kind="FINAL", status="DRAFT", created_by="lead", body_sha256="h1", team_ids=["lead", "aud2"])
        base.update(kw); return wf.ReportState(**base)

    def test_submit_requires_all_initials_from_team(self):
        with self.assertRaises(wf.WorkflowError): wf.can_submit_final(self.st(initialed_ids={"lead"}), "lead")
        wf.can_submit_final(self.st(initialed_ids={"lead", "aud2"}), "lead")
        with self.assertRaises(wf.WorkflowError): wf.can_submit_final(self.st(initialed_ids={"lead", "aud2"}), "outsider")
        with self.assertRaises(wf.WorkflowError): wf.can_initial(self.st(), "outsider")
        wf.can_initial(self.st(), "aud2")

    def test_review_and_approval_are_independent_of_team(self):
        s = self.st(status="IN_REVIEW")
        wf.can_review(s, "contralor")
        for actor in ("lead", "aud2"):
            with self.assertRaises(wf.WorkflowError): wf.can_review(s, actor)
        with self.assertRaises(wf.WorkflowError): wf.can_review(self.st(status="DRAFT"), "contralor")

    def test_signing_order_and_integrity(self):
        s = self.st(status="APPROVED", approved_by="contralor", approved_body_sha256="h1")
        with self.assertRaises(wf.WorkflowError): wf.can_sign(s, "gerente", "GERENTE_CI")          # primero el Contralor
        with self.assertRaises(wf.WorkflowError): wf.can_sign(s, "otro", "CONTRALOR")              # firma quien aprobó
        wf.can_sign(s, "contralor", "CONTRALOR")
        s.signed_roles["CONTRALOR"] = "contralor"
        wf.can_sign(s, "gerente", "GERENTE_CI")
        with self.assertRaises(wf.WorkflowError): wf.can_sign(s, "contralor", "GERENTE_CI")        # el gerente es otra persona
        with self.assertRaises(wf.WorkflowError): wf.can_sign(s, "contralor", "CONTRALOR")         # no se firma dos veces
        s.signed_roles["GERENTE_CI"] = "gerente"; self.assertTrue(wf.is_fully_signed(s))
        s2 = self.st(status="APPROVED", approved_by="contralor", approved_body_sha256="OTRO")
        with self.assertRaises(wf.WorkflowError): wf.can_sign(s2, "contralor", "CONTRALOR")        # contenido cambió tras aprobar
        with self.assertRaises(wf.WorkflowError): wf.can_sign(self.st(status="APPROVED", approved_by="lead", approved_body_sha256="h1"), "lead", "CONTRALOR")

    def test_previo_and_pac(self):
        wf.can_send_previo(self.st(kind="PREVIO"), "lead")
        with self.assertRaises(wf.WorkflowError): wf.can_send_previo(self.st(kind="PREVIO", status="SENT"), "lead")
        with self.assertRaises(wf.WorkflowError): wf.can_send_pac(self.st(status="APPROVED"))
        with self.assertRaises(wf.WorkflowError): wf.can_send_pac(None)
        wf.can_send_pac(self.st(status="SIGNED"))

    def test_edit_only_draft_or_returned(self):
        wf.can_edit(self.st()); wf.can_edit(self.st(status="RETURNED"))
        with self.assertRaises(wf.WorkflowError): wf.can_edit(self.st(status="APPROVED"))


if __name__ == "__main__":
    unittest.main()
