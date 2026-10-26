"""Codificación institucional y consolidación de observaciones por dominio."""
import unittest

from app.modules.engagement import codification as cod
from app.modules.engagement import observation_rules as rules


class CodificationTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(cod.file_code("S", "SC", 1, 2026), "S-SC-001-2026")
        self.assertEqual(cod.audit_code("S-SC-001-2026", 2), "S-SC-001-2026-A2")
        self.assertEqual(cod.report_code(cod.report_prefix("P", "S", "G", "SC"), 12, 2026), "P-S-G-SC-012-2026")
        self.assertEqual(cod.file_code("LC", "INSG", 3, 2026), "LC-INSG-003-2026")

    def test_defaults_by_domain(self):
        self.assertEqual(cod.file_fields({}, "SISTEMAS"), {"audit_type": "S", "company": "SC"})
        self.assertEqual(cod.file_fields({}, "FINANCIERA", "SUCURSAL")["audit_type"], "A")
        self.assertEqual(cod.report_fields({}, "SISTEMAS"), {"plan_type": "P", "process": "S", "frequency": "G", "report_company": "SC"})
        self.assertEqual(cod.report_fields({}, "FINANCIERA")["process"], "F")

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(cod.CodeError):
            cod.file_fields({"audit_type": "P"}, "SISTEMAS")
        with self.assertRaises(cod.CodeError):
            cod.file_fields({"company": "XX"}, "GENERAL")
        with self.assertRaises(cod.CodeError):
            cod.report_fields({"frequency": "Z"}, "GENERAL")


class ConsolidationTests(unittest.TestCase):
    def crit(self, code, text):
        return {"code": code, "text": text, "section": "Accesos", "weight": 1}

    def test_gaps_of_same_domain_become_one_observation(self):
        rows = [
            (self.crit("TI032", "¿Existe un procedimiento formal para la baja de cuentas de usuario?"), {"control": "NO", "documental": "NO"}, None, "i1"),
            (self.crit("TI035", "¿El uso de perfiles con privilegios elevados está restringido?"), {"control": "SI", "documental": "NO"}, None, "i2"),
            (self.crit("TI052", "¿Se ejecutan pruebas periódicas de restauración de respaldos?"), {"control": "NO", "documental": "NO"}, None, "i3"),
            (self.crit("TI060", "¿Se revisa la conciliación de licencias?"), {"control": "SI", "documental": "SI", "evidencia": "ACTUALIZADO"}, None, "i4"),
        ]
        out = rules.consolidate(rows)
        self.assertEqual(len(out), 2)
        accesos = next(o for o in out if o["domain"] == "accesos")
        self.assertEqual(accesos["covered_items"], ["i1", "i2"])
        self.assertEqual(accesos["risk"], "ALTO")
        self.assertIn("2 controles", accesos["title"])
        self.assertIn("TI032", accesos["condition"]); self.assertIn("TI035", accesos["recommendation"])
        single = next(o for o in out if o["domain"] == "respaldos")
        self.assertEqual(single["covered_items"], ["i3"])
        for k in ("risk", "title", "condition", "criteria", "cause", "effect", "recommendation"):
            self.assertTrue(accesos[k] and single[k], k)
        self.assertEqual(out[0]["risk"], "ALTO")

    def test_condition_respects_length_limit(self):
        rows = [(self.crit(f"TI{i:03d}", "¿Se revisan los accesos privilegiados " + "x" * 200 + "?"), {"control": "NO"}, None, f"i{i}")
                for i in range(80)]
        o = rules.consolidate(rows)[0]
        self.assertLessEqual(len(o["condition"]), rules.MAX_CONDITION)
        self.assertEqual(len(o["covered_items"]), 80)


if __name__ == "__main__":
    unittest.main()
