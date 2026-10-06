import unittest
from datetime import date
from decimal import Decimal as Dec

from app.modules.analytics import calculations as C
from app.modules.analytics.service import build_kpis


class CalcTest(unittest.TestCase):
    def test_no_binary_float_noise(self):
        self.assertEqual(C.sum_exact([0.1, 0.2]), Dec("0.3"))
        self.assertNotEqual(0.1 + 0.2, 0.3)                    # el problema que se evita

    def test_rounding_half_up(self):
        self.assertEqual(C.money("2.675"), Dec("2.68"))        # float/round() daría 2.67
        self.assertEqual(C.money("2.674"), Dec("2.67"))
        self.assertEqual(C.money("1,5"), Dec("1.50"))

    def test_earned_and_unearned_premium(self):
        s, e = date(2026, 1, 1), date(2027, 1, 1)               # 365 días
        self.assertEqual(C.earned_premium(1000, s, e, date(2026, 3, 15)), Dec("200.00"))   # 73 días de 365 = 20 %
        self.assertEqual(C.earned_premium(1000, s, e, date(2026, 1, 1)), Dec("0.00"))
        self.assertEqual(C.earned_premium(1000, s, e, date(2025, 6, 1)), Dec("0.00"))      # antes de la vigencia
        self.assertEqual(C.earned_premium(1000, s, e, date(2030, 1, 1)), Dec("1000.00"))   # después
        for as_of in (date(2026, 4, 10), date(2026, 9, 30)):
            self.assertEqual(C.earned_premium(1000, s, e, as_of) + C.unearned_premium_reserve(1000, s, e, as_of), Dec("1000.00"))

    def test_leap_year_term(self):
        self.assertEqual(C.earned_premium(366, date(2028, 1, 1), date(2029, 1, 1), date(2028, 7, 1)), Dec("182.00"))
        with self.assertRaises(ValueError):
            C.earned_premium(100, date(2026, 1, 1), date(2026, 1, 1), date(2026, 1, 1))

    def test_ratios(self):
        inc = C.incurred_claims(600, 300, 200)                  # 700
        self.assertEqual(inc, Dec("700.00"))
        self.assertEqual(C.loss_ratio(inc, 1000), Dec("0.7000"))
        self.assertEqual(C.combined_ratio(inc, 250, 1000), Dec("0.9500"))
        self.assertIsNone(C.loss_ratio(inc, 0))                 # nunca se inventa un valor

    def test_variance(self):
        self.assertEqual(C.variance(110, 100), {"absoluta": Dec("10.00"), "porcentual": Dec("0.1000")})
        self.assertIsNone(C.variance(5, 0)["porcentual"])

    def test_currencies_are_never_mixed(self):
        with self.assertRaises(ValueError):
            C.Money(10, "USD") + C.Money(10, "VES")
        self.assertEqual((C.Money(10, "USD").convert("VES", Dec("36.5"))).amount, Dec("365.0"))
        with self.assertRaises(ValueError):
            C.Money(1, "USD").convert("VES", Dec("0"))

    def test_invalid_amount(self):
        with self.assertRaises(ValueError):
            C.D("abc")

    def test_kpis(self):
        k = build_kpis(written_premium=1200, earned_premium=1000, paid_claims=600, reserve_start=200, reserve_end=300,
                       expenses=250, claim_count=3, exposed_policies=30,
                       findings_by_severity={"CRITICAL": 1, "HIGH": 1, "MEDIUM": 2, "LOW": 0},
                       findings_open=3, findings_closed_30d=1)
        self.assertEqual(k["siniestralidad"], "0.7000")
        self.assertEqual(k["ratio_combinado"], "0.9500")
        self.assertEqual(k["severidad"], "200.00")
        self.assertEqual(k["frecuencia"], "0.1000")
        self.assertEqual(k["hallazgos"]["criticos_y_altos_pct"], "0.5000")


if __name__ == "__main__":
    unittest.main()
