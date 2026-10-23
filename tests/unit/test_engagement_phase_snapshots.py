import json
import unittest
from decimal import Decimal

from app.modules.engagement.score_snapshots import build_scorecard
from app.modules.engagement import scoring


class PhaseScorecardTests(unittest.TestCase):
    def setUp(self):
        self.audit = {
            "id": "00000000-0000-0000-0000-000000000201",
            "code": "AUD-TEST-0001",
            "audit_domain": "SISTEMAS",
            "phase": "TRABAJO_CAMPO",
            "manual_score": Decimal("77.50"),
            "manual_reason": "Ajuste justificado para la prueba",
        }
        self.worksheets = [{
            "id": "00000000-0000-0000-0000-000000000301",
            "title": "Control de acceso",
            "kind": "SISTEMAS",
            "line": "ERP_TI",
            "criteria": [
                {"code": "C1", "text": "Control de prueba", "weight": 1}
            ],
            "manual_score": None,
            "manual_reason": None,
            "items": [
                {
                    "id": "00000000-0000-0000-0000-000000000401",
                    "ref": "CTRL-01",
                    "results": {"C1": "CUMPLE"},
                    "manual_score": Decimal("80.00"),
                    "manual_reason": "Evidencia compensatoria documentada",
                    "observation": "Comentario del auditor",
                    "info_exception": None,
                },
                {
                    "id": "00000000-0000-0000-0000-000000000402",
                    "ref": "CTRL-02",
                    "results": {"C1": "NO_CUMPLE"},
                    "manual_score": None,
                    "manual_reason": None,
                    "observation": None,
                    "info_exception": None,
                },
            ],
        }]

    def test_snapshot_preserves_global_sheet_and_item_scores(self):
        snapshot = build_scorecard(
            self.audit,
            self.worksheets,
            scoring.DEFAULT_THRESHOLDS,
        )

        self.assertEqual(snapshot["audit_code"], "AUD-TEST-0001")
        self.assertEqual(snapshot["phase"], "TRABAJO_CAMPO")
        self.assertEqual(snapshot["overall"]["manual_score"], 77.5)
        self.assertEqual(snapshot["overall"]["items"], 2)
        self.assertEqual(snapshot["overall"]["scored"], 2)
        self.assertEqual(snapshot["overall"]["auto"], 40.0)
        self.assertEqual(snapshot["overall"]["final"], 77.5)

        sheet = snapshot["worksheets"][0]
        self.assertEqual(sheet["items"], 2)
        self.assertEqual(sheet["scored"], 2)
        self.assertEqual(sheet["auto"], 40.0)
        self.assertEqual(sheet["final"], 40.0)
        self.assertEqual(sheet["items_detail"][0]["auto_score"], 100.0)
        self.assertEqual(sheet["items_detail"][0]["final_score"], 80.0)
        self.assertEqual(
            sheet["items_detail"][0]["manual_reason"],
            "Evidencia compensatoria documentada",
        )

        # El contenido debe poder persistirse como JSON sin convertir
        # puntuaciones NUMERIC/Decimal en cadenas.
        encoded = json.dumps(snapshot, ensure_ascii=False)
        restored = json.loads(encoded)
        self.assertIsInstance(restored["overall"]["final"], float)
        self.assertIsInstance(restored["worksheets"][0]["items_detail"][0]["final_score"], float)

    def test_empty_audit_has_no_numeric_score(self):
        snapshot = build_scorecard(
            {"code": "AUD-EMPTY", "phase": "PLANIFICACION"},
            [],
            scoring.DEFAULT_THRESHOLDS,
        )

        self.assertIsNone(snapshot["overall"]["auto"])
        self.assertIsNone(snapshot["overall"]["final"])
        self.assertEqual(snapshot["overall"]["items"], 0)
        self.assertEqual(snapshot["worksheets"], [])


if __name__ == "__main__":
    unittest.main()
