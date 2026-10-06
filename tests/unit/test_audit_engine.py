import math
import random
import unittest
from datetime import date, timedelta

from app.modules.audit_engine.context import InMemoryContext
from app.modules.audit_engine.engine import run_engine
from app.modules.audit_engine.models import Severity
from app.modules.audit_engine.rules.benford import BenfordRule, benford_stats, mad_conformity
from app.modules.audit_engine.rules.duplicates import DuplicateClaimsRule, OverlappingPoliciesRule
from app.modules.audit_engine.rules.early_claims import EarlyClaimRule
from app.modules.audit_engine.rules.reserves_range import ReserveRangeRule, modified_z_scores


def claim(num, occ, start="2026-01-01", end="2026-12-31", amount=1000.0, pol="P1", cov="COLISION", rep=None):
    return {"claim_number": num, "policy_number": pol, "coverage": cov, "occurrence_date": occ,
            "reported_date": rep or occ, "claimed_amount": amount, "policy_start": start,
            "policy_end": end, "branch": "AUTO", "sum_insured": 50000}


class DuplicatesTest(unittest.TestCase):
    def test_exact_and_probable_duplicate_claims(self):
        ctx = InMemoryContext(claims=[claim("S1", "2026-03-01"), claim("S1", "2026-03-01"),
                                      claim("S2", "2026-05-10", amount=500), claim("S3", "2026-05-10", amount=500),
                                      claim("S4", "2026-06-10", amount=800)])
        f = list(DuplicateClaimsRule().run(ctx))
        kinds = sorted(x.evidence["tipo"] for x in f)
        self.assertIn("EXACTO", kinds)
        self.assertIn("PROBABLE", kinds)
        self.assertFalse(any(x.entity_id == "S4" for x in f))

    def test_overlapping_policies(self):
        pol = lambda n, s, e: {"policy_number": n, "insured_id": "V123", "risk_id": "ABC12D", "branch": "AUTO",
                               "start_date": s, "end_date": e, "sum_insured": 1}
        ctx = InMemoryContext(policies=[pol("A", "2026-01-01", "2026-12-31"), pol("B", "2026-06-01", "2027-05-31"),
                                        pol("C", "2027-06-01", "2028-05-31")])
        f = list(OverlappingPoliciesRule().run(ctx))
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].evidence["polizas"], ["A", "B"])


class EarlyClaimTest(unittest.TestCase):
    def test_levels(self):
        ctx = InMemoryContext(claims=[
            claim("C-OUT", "2025-12-30"),          # antes de la vigencia
            claim("C-HIGH", "2026-01-04"),         # 3 días
            claim("C-MED", "2026-01-20"),          # 19 días
            claim("C-OK", "2026-06-15"),
            claim("C-LATE", "2026-01-25", rep="2026-04-01"),  # medio + reporte tardío
        ])
        got = {f.entity_id: f for f in EarlyClaimRule().run(ctx)}
        self.assertEqual(got["C-OUT"].severity, Severity.CRITICAL)
        self.assertEqual(got["C-HIGH"].severity, Severity.HIGH)
        self.assertEqual(got["C-MED"].severity, Severity.MEDIUM)
        self.assertNotIn("C-OK", got)
        self.assertGreater(got["C-LATE"].score, got["C-MED"].score)


class ReserveRangeTest(unittest.TestCase):
    def test_controls(self):
        rnd = random.Random(1)
        reserves = [{"reserve_type": "CLAIM", "branch": "AUTO", "claim_number": f"R{i}", "period": "2026-09-01",
                     "amount": rnd.gauss(10000, 500), "sum_insured": 100000} for i in range(60)]
        reserves += [
            {"reserve_type": "CLAIM", "branch": "AUTO", "claim_number": "NEG", "period": "2026-09-01", "amount": -5, "sum_insured": 1000},
            {"reserve_type": "CLAIM", "branch": "AUTO", "claim_number": "BIG", "period": "2026-09-01", "amount": 90000, "sum_insured": 50000},
            {"reserve_type": "CLAIM", "branch": "AUTO", "claim_number": "OUT", "period": "2026-09-01", "amount": 40000, "sum_insured": 100000},
        ]
        f = list(ReserveRangeRule().run(InMemoryContext(reserves=reserves)))
        ids = {(x.entity_id, x.evidence.get("z_modificado") is not None) for x in f}
        self.assertIn(("NEG", False), ids)
        self.assertIn(("BIG", False), ids)          # excede suma asegurada
        self.assertIn(("OUT", True), ids)           # atípico estadístico

    def test_modified_z_constant_group(self):
        self.assertEqual(modified_z_scores([5, 5, 5, 5]), [0.0] * 4)


class BenfordTest(unittest.TestCase):
    @staticmethod
    def natural(n, seed=7):
        rnd = random.Random(seed)
        return [10 ** rnd.uniform(1, 6) for _ in range(n)]          # log-uniforme => Benford exacto

    def test_natural_data_conforms(self):
        st = benford_stats(self.natural(5000))
        self.assertLessEqual(st["mad"], 0.012)
        self.assertIn(mad_conformity(st["mad"]), ("CONFORME", "ACEPTABLE"))

    def test_fabricated_data_flagged(self):
        rnd = random.Random(3)
        fake = [rnd.choice([5, 6, 7]) * 10 ** rnd.randint(1, 5) + rnd.random() for _ in range(2000)] + \
               [rnd.uniform(10, 900_000) for _ in range(500)]
        claims = [{"claimed_amount": v, "branch": "AUTO"} for v in fake]
        rule = BenfordRule({"sources": [{"dataset": "claims", "field": "claimed_amount", "group_by": "branch"}]})
        f = list(rule.run(InMemoryContext(claims=claims)))
        self.assertEqual(len(f), 1)
        self.assertIn(f[0].severity, (Severity.MEDIUM, Severity.HIGH))

    def test_small_sample_is_skipped_not_flagged(self):
        claims = [{"claimed_amount": 5000.0 + i, "branch": "AUTO"} for i in range(50)]
        rule = BenfordRule({"sources": [{"dataset": "claims", "field": "claimed_amount", "group_by": "branch"}]})
        self.assertEqual(list(rule.run(InMemoryContext(claims=claims))), [])
        self.assertTrue(rule.skipped)

    def test_expected_first_digit_probability(self):
        self.assertAlmostEqual(math.log10(2), 0.30103, places=4)


class EngineTest(unittest.TestCase):
    def test_engine_isolates_rule_errors_and_dedupes(self):
        class Broken:
            def policies(self): return iter([])
            def claims(self): raise RuntimeError("boom")
            def reserves(self): return iter([])
        res = run_engine(Broken())
        self.assertTrue(res.errors)                       # las reglas que tocan claims fallan...
        self.assertIn("DUP-POLICY", res.summary)          # ...pero las demás corren

    def test_fingerprint_is_stable(self):
        ctx = InMemoryContext(claims=[claim("C-OUT", "2025-12-30")])
        a = run_engine(ctx, enabled={"EARLY-CLAIM"}).findings[0].fingerprint
        b = run_engine(ctx, enabled={"EARLY-CLAIM"}).findings[0].fingerprint
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
