import unittest

from app.modules.reporting import workflow as wf
from app.modules.reporting.dictamen_pdf import build_dictamen_pdf


def state(status, drafted="u1", approved=None, body=None, approved_hash=None):
    body = body or {"title": "X"}
    return wf.ReportState("r1", status, drafted, approved, body, approved_hash)


class WorkflowTest(unittest.TestCase):
    def test_drafter_cannot_approve_or_sign(self):
        with self.assertRaises(wf.WorkflowError):
            wf.can_approve(state(wf.SUBMITTED), "u1")
        h = wf.body_hash({"title": "X"})
        with self.assertRaises(wf.WorkflowError):
            wf.can_sign(state(wf.APPROVED, approved_hash=h), "u1")

    def test_happy_path(self):
        wf.can_submit(state(wf.DRAFT), "u1")
        wf.can_approve(state(wf.SUBMITTED), "u2")
        wf.can_sign(state(wf.APPROVED, approved_hash=wf.body_hash({"title": "X"})), "u2")

    def test_content_changed_after_approval_blocks_signing(self):
        r = state(wf.APPROVED, approved_hash=wf.body_hash({"title": "X"}), body={"title": "MODIFICADO"})
        with self.assertRaises(wf.WorkflowError):
            wf.can_sign(r, "u2")

    def test_cannot_skip_states(self):
        with self.assertRaises(wf.WorkflowError):
            wf.can_sign(state(wf.DRAFT), "u2")
        with self.assertRaises(wf.WorkflowError):
            wf.can_approve(state(wf.SIGNED), "u2")

    def test_hash_is_canonical(self):
        self.assertEqual(wf.body_hash({"a": 1, "b": 2}), wf.body_hash({"b": 2, "a": 1}))


class PdfTest(unittest.TestCase):
    def test_pdf_generation(self):
        pdf = build_dictamen_pdf({"folio": "DC-2026-001", "kind": "DICTAMEN", "title": "Prueba <&>",
                                  "company": "Aseguradora Ejemplo", "date": "2026-09-30", "author": "A. Muñoz",
                                  "findings": [{"rule_code": "EARLY-CLAIM", "severity": "HIGH", "entity_id": "S1",
                                                "message": "Siniestro a 3 días del inicio"}],
                                  "conclusion": "Se recomienda revisión.", "body_sha256": "ab" * 32})
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 1500)


if __name__ == "__main__":
    unittest.main()
