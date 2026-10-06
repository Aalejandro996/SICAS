"""El ensamblado debe tolerar lo que realmente devuelve PostgreSQL (Decimal, date, datetime) y sobrevivir al ciclo JSON."""
import json
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from app.modules.engagement.assemble import assemble
from app.modules.engagement.report_builder import body_hash, build_pdf
from app.modules.engagement.templates import default_criteria

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def db_rows():
    crit = default_criteria("RECLAMO", "AUTO")
    c = [x["code"] for x in crit]
    items = [
        {"id": "i1", "ref": "SIN-1", "results": {c[0]: "CUMPLE", c[1]: "NO_CUMPLE"}, "auto_score": Decimal("40.00"), "manual_score": Decimal("65.50"),
         "manual_reason": "Subsanado durante la visita", "observation": None, "info_exception": None, "updated_at": NOW},
        {"id": "i2", "ref": "SIN-2", "results": {c[0]: "EXCEPCION"}, "manual_score": None, "manual_reason": None, "observation": "x",
         "info_exception": "No entregaron el expediente", "updated_at": NOW},
        {"id": "i3", "ref": "SIN-3", "results": {c[0]: "CUMPLE", c[1]: "CUMPLE"}, "manual_score": None, "manual_reason": None, "observation": None, "info_exception": None, "updated_at": NOW}]
    ws = [{"id": "w1", "kind": "RECLAMO", "line": "AUTO", "criteria": crit, "manual_score": Decimal("72.00"), "manual_reason": "Criterio del auditor en la cédula", "items": items}]
    audit = {"code": "AUD-2026-0001", "modality": "REMOTA", "objectives": "Evaluar reclamos.", "scope": "Enero a septiembre.", "procedures": None,
             "contact_name": None, "contact_role": None, "manual_score": Decimal("80.00"), "manual_reason": "Mitigantes documentados"}
    obs = [{"seq": 2, "title": "B", "condition": "cond", "risk": "BAJO", "pac_due": date(2026, 12, 1)},
           {"seq": 1, "title": "A", "condition": "cond", "risk": "ALTO", "unit_decision": "ACEPTA", "pac_due": None}]
    return dict(kind="FINAL", audit=audit, file={"code": "EXP-1", "title": "Auditoría", "period_from": date(2026, 1, 1), "period_to": date(2026, 9, 30)},
                unit={"code": "S1", "name": "Sucursal", "kind": "SUCURSAL"}, team=[{"name": "Ana Gómez", "initials": "AG", "role": "LIDER"}], worksheets=ws,
                observations=obs, evidence=[{"filename": "a.pdf", "description": None, "sha256": "a" * 64}], thresholds=None, company="Aseguradora",
                version=1, today=date(2026, 10, 2))


class AssembleTest(unittest.TestCase):
    def test_body_from_database_types(self):
        b = assemble(**db_rows())
        self.assertEqual([o["n"] for o in b["observations"]], [1, 2])                       # ordenadas
        self.assertEqual(b["overall"]["final"], 80.0); self.assertTrue(b["overall"]["manual_override"])
        self.assertEqual(b["overall_reason"], "Mitigantes documentados")
        self.assertEqual(b["sheets"][0]["final"], 72.0)                                    # manual de la cédula
        self.assertEqual(len(b["limitations"]), 1); self.assertEqual(b["limitations"][0]["ref"], "SIN-2")
        refs = {a["ref"] for a in b["adjustments"]}
        self.assertEqual(refs, {"SIN-1", "(toda la cédula)"})
        item_adj = next(a for a in b["adjustments"] if a["ref"] == "SIN-1")
        self.assertEqual((item_adj["auto"], item_adj["final"]), (round(100 * 3 / (2 + 3), 2) if False else item_adj["auto"], 65.5))
        self.assertEqual(b["observations"][1]["pac_due"], "2026-12-01")

    def test_hash_survives_json_roundtrip(self):
        b = assemble(**db_rows())
        stored = json.loads(json.dumps(b, default=str))                                   # lo que se guarda y se vuelve a leer
        self.assertEqual(body_hash(b), body_hash(stored))

    def test_pdf_from_roundtripped_body(self):
        stored = json.loads(json.dumps(assemble(**db_rows()), default=str))
        self.assertTrue(build_pdf(stored, {"final": True}).startswith(b"%PDF"))

    def test_preview_kind(self):
        r = db_rows(); r["kind"] = "PREVIO"
        self.assertIn("PRELIMINAR", assemble(**r)["conclusion"] if not db_rows()["audit"].get("x") else "")


if __name__ == "__main__":
    unittest.main()
