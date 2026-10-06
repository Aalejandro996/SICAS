"""Prueba de extremo a extremo (sin base de datos): datos sintéticos -> validación -> motor de reglas."""
import importlib.util
import pathlib
import unittest
from collections import Counter

from app.modules.audit_engine.context import InMemoryContext
from app.modules.audit_engine.engine import run_engine
from app.modules.ingestion.validators import normalize_row, validate_row

ROOT = pathlib.Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sample_data_gen", ROOT / "scripts" / "generate_sample_data.py")
gen = importlib.util.module_from_spec(spec); spec.loader.exec_module(gen)

DATASET = {"polizas": "policies", "siniestros": "claims", "reservas": "reserves", "pagos": "payments"}


class SampleDataEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = gen.generate()
        # Igual que la carga real: validar y normalizar; el SQL une cada siniestro con su póliza (LEFT JOIN)
        norm = {}
        for name, ds in DATASET.items():
            rows = []
            for r in cls.data[name]:
                assert validate_row(ds, r) == [], (ds, r, validate_row(ds, r))
                rows.append(normalize_row(ds, r))
            norm[ds] = rows
        first = {}
        for p in norm["policies"]:
            first.setdefault(p["policy_number"], p)
        claims = []
        for c in norm["claims"]:
            p = first.get(c["policy_number"])
            claims.append({**c, "policy_start": p["start_date"] if p else None, "policy_end": p["end_date"] if p else None,
                           "branch": p["branch"] if p else None, "sum_insured": p["sum_insured"] if p else None})
        ctx = InMemoryContext(policies=norm["policies"], claims=claims, reserves=norm["reserves"], payments=norm["payments"],
                              watchlist={"V99999991": "LISTA-PRUEBA"})
        cls.res = run_engine(ctx)
        cls.by_rule = Counter(f.rule_code for f in cls.res.findings)

    def test_all_sample_rows_are_valid_and_no_rule_crashed(self):
        self.assertEqual(self.res.errors, [])

    def test_each_rule_fires_on_seeded_anomalies(self):
        for rule in ("DUP-CLAIM", "DUP-POLICY", "EARLY-CLAIM", "RESERVE-RANGE", "BENFORD-1D",
                     "LCFT-THRESHOLD", "LCFT-STRUCTURING", "LCFT-WATCHLIST"):
            self.assertGreater(self.by_rule[rule], 0, f"{rule} no detectó nada: {dict(self.by_rule)}")

    def test_seeded_counts_are_found(self):
        f = self.res.findings
        crit_early = [x for x in f if x.rule_code == "EARLY-CLAIM" and x.severity.value == "CRITICAL"]
        self.assertGreaterEqual(len(crit_early), 5)                                   # 5 fuera de vigencia
        orphans = [x for x in f if x.rule_code == "EARLY-CLAIM" and x.identity_facts.get("tipo") == "HUERFANO"]
        self.assertEqual(len(orphans), 4)
        self.assertEqual(len([x for x in f if x.rule_code == "LCFT-THRESHOLD"]), 3)
        self.assertEqual(len([x for x in f if x.rule_code == "LCFT-STRUCTURING"]), 1)
        self.assertEqual(len([x for x in f if x.rule_code == "LCFT-WATCHLIST"]), 3)   # 1 póliza + 2 pagos
        neg = [x for x in f if x.rule_code == "RESERVE-RANGE" and x.identity_facts.get("control") == "NEG"]
        self.assertEqual(len(neg), 3)
        pol_dups = [x for x in f if x.rule_code == "DUP-POLICY"]
        self.assertGreaterEqual(len(pol_dups), 2)                                     # repetida + solapada

    def test_benford_flags_only_the_fabricated_group(self):
        flagged = [x.entity_id for x in self.res.findings if x.rule_code == "BENFORD-1D"]
        self.assertIn("claims.claimed_amount[HOGAR/USD]", flagged)
        self.assertFalse([e for e in flagged if "VIDA" in e or "SALUD" in e or "AUTO" in e],
                         f"falsos positivos de Benford en datos naturales: {flagged}")

    def test_findings_are_deduplicated(self):
        fps = [x.fingerprint for x in self.res.findings]
        self.assertEqual(len(fps), len(set(fps)))

    def test_deterministic(self):
        again = gen.generate()
        self.assertEqual(again["pagos"], self.data["pagos"])


if __name__ == "__main__":
    unittest.main()
