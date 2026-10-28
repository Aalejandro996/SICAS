"""Auditoría de Sistemas: controles de la carta de documentación y cierre de las fases 2 y 3."""
import unittest

from app.modules.engagement import systems_docs as sd


def item(lev_doc="SI", doc_closed=None, current=None, ref="TI001"):
    pr = {"LEVANTAMIENTO": {"results": {ref: {"control": "SI", "documental": lev_doc, "evidencia": "ACTUALIZADO"}}}}
    if doc_closed is not None:
        pr["DOCUMENTACION"] = {"results": {ref: doc_closed}}
    return {"id": "i-" + ref, "ref": ref, "results": {ref: current or {}}, "phase_results": pr}


class LetterTests(unittest.TestCase):
    def test_letter_is_what_was_declared_documented(self):
        self.assertTrue(sd.in_letter(item("SI")))
        self.assertFalse(sd.in_letter(item("NO")))

    def test_documentation_maps_to_the_40_30_30_fields(self):
        for status, (doc, ev) in sd.DOC_STATUS.items():
            r = sd.documentation_result(item(), {"doc_status": status})
            self.assertEqual((r["control"], r["documental"], r["evidencia"]), ("SI", doc, ev))

    def test_status_of_records_before_the_change(self):
        self.assertEqual(sd.doc_status_of({"documental": "SI", "evidencia": "DESACTUALIZADO"}), "DESACTUALIZADA")
        self.assertEqual(sd.doc_status_of({"documental": "NO"}), "NO_ENTREGADA")
        self.assertIsNone(sd.doc_status_of({}))

    def test_field_outcome(self):
        self.assertEqual(sd.field_outcome({"q1": "SI", "q2": "SI", "q3": "SI"}), "CUMPLE")
        self.assertEqual(sd.field_outcome({"q1": "NO", "q2": "SI", "q3": "NO"}), "PARCIAL")
        self.assertEqual(sd.field_outcome({"q1": "NO", "q2": "NO", "q3": "NO"}), "NO_CUMPLE")
        self.assertIsNone(sd.field_outcome({"q1": "SI", "q2": "", "q3": "SI"}))


class PendingTests(unittest.TestCase):
    def test_documentation_phase_needs_every_letter_control(self):
        items = [item(ref="A"), item(ref="B", current={"doc_status": "SIN_RESPUESTA"}), item("NO", ref="C")]
        self.assertEqual(sd.pending(items, "DOCUMENTACION"), ["A"])

    def test_field_phase_needs_answers_or_justification(self):
        docs = {"control": "SI", "doc_status": "ACTUALIZADA"}
        nodoc = {"control": "SI", "doc_status": "SIN_RESPUESTA"}
        done = item(ref="A", doc_closed=docs, current={"outcome": "CUMPLE"})
        missing = item(ref="B", doc_closed=docs, current={"q1": "SI"})
        short = item(ref="C", doc_closed=nodoc, current={"outcome": "SIN_DOC", "justification": "corto"})
        ok = item(ref="D", doc_closed=nodoc, current={"outcome": "SIN_DOC", "justification": "La unidad no respondió la carta."})
        legacy = item(ref="E", doc_closed={"control": "SI", "documental": "SI"}, current={"control": "SI", "documental": "SI"})
        self.assertEqual(sd.pending([done, missing, short, ok, legacy], "PRUEBAS_CAMPO"), ["B", "C"])


if __name__ == "__main__":
    unittest.main()
