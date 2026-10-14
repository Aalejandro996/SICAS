import logging
from app.core.logging_redaction import RedactingFilter, redact
import unittest
from decimal import Decimal as Dec

from app.modules.audit_engine.context import InMemoryContext
from app.modules.audit_engine.engine import run_engine
from app.modules.audit_engine.models import Severity
from app.modules.audit_engine.rules.early_claims import EarlyClaimRule
from app.modules.audit_engine.rules.lcft import CashThresholdRule, StructuringRule, WatchlistRule
from app.modules.audit_engine.rules.reserves_range import ReserveRangeRule
from app.modules.ingestion.reconcile import ControlTotals, reconcile
from app.modules.ingestion.validators import normalize_row, validate_row


def pay(pid, amount, day, payer="V-12.345.678", cur="USD", method="CASH"):
    return {"payment_id": pid, "policy_number": "P1", "payer_id": payer, "amount": amount, "currency": cur,
            "method": method, "paid_at": f"2026-09-{day:02d}"}


class LcftTest(unittest.TestCase):
    def test_threshold(self):
        ctx = InMemoryContext(payments=[pay("A", "10000", 1), pay("B", "9999.99", 2), pay("C", "20000", 3, method="TRANSFER")])
        f = list(CashThresholdRule().run(ctx))
        self.assertEqual([x.entity_id for x in f], ["A"])           # transferencia fuera del alcance por defecto

    def test_unknown_currency_is_skipped_and_reported_not_guessed(self):
        rule = CashThresholdRule()
        self.assertEqual(list(rule.run(InMemoryContext(payments=[pay("A", "99999999", 1, cur="VES")]))), [])
        self.assertTrue(rule.skipped)

    def test_structuring_detects_split_payments(self):
        ctx = InMemoryContext(payments=[pay("1", "4000", 1), pay("2", "3500", 5), pay("3", "3000", 9),
                                        pay("4", "100", 28, payer="V-99999999")])
        f = list(StructuringRule().run(ctx))
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].evidence["total"], "10500.00" if False else str(Dec("10500")))
        self.assertEqual(f[0].entity_id, "V12345678")               # identificador normalizado

    def test_structuring_ignores_spread_out_payments(self):
        ctx = InMemoryContext(payments=[pay("1", "4000", 1), pay("2", "4000", 20), pay("3", "4000", 28)])
        late = list(StructuringRule({"window_days": 5}).run(ctx))
        self.assertEqual(late, [])

    def test_watchlist_matches_normalized_ids(self):
        ctx = InMemoryContext(
            policies=[{"policy_number": "P1", "insured_id": "j-12345678-9", "risk_id": None, "branch": "AUTO",
                       "start_date": "2026-01-01", "end_date": "2026-12-31", "sum_insured": 1}],
            payments=[pay("A", "10", 1, payer="v 12.345.678")],
            watchlist={"J123456789": "LISTA-X", "V12345678": "LISTA-Y"})
        f = list(WatchlistRule().run(ctx))
        self.assertEqual({x.entity_type for x in f}, {"policy", "payment"})
        self.assertTrue(all(x.severity == Severity.CRITICAL for x in f))

    def test_engine_runs_lcft_rules(self):
        res = run_engine(InMemoryContext(payments=[pay("A", "50000", 1)]), enabled={"LCFT-THRESHOLD"})
        self.assertEqual(len(res.findings), 1)


class IntegrityRulesTest(unittest.TestCase):
    def test_orphan_claim_flagged(self):
        c = {"claim_number": "S9", "policy_number": "NOEXISTE", "occurrence_date": "2026-05-01", "reported_date": "2026-05-02",
             "claimed_amount": 10, "policy_start": None, "policy_end": None}
        f = list(EarlyClaimRule().run(InMemoryContext(claims=[c])))
        self.assertEqual(f[0].evidence["poliza"], "NOEXISTE")

    def test_reserves_are_not_compared_across_currencies(self):
        # Cada moneda es homogénea (sin atípicos internos); VES vale 36 veces más que USD.
        mk = lambda cur, scale, i: {"reserve_type": "CLAIM", "branch": "AUTO", "claim_number": f"{cur}{i}",
                                    "period": "2026-09-01", "amount": scale * (1 + 0.002 * i), "sum_insured": scale * 100,
                                    "currency": cur}
        rows = [mk("USD", 1000, i) for i in range(60)] + [mk("VES", 36000, i) for i in range(12)]
        z = [x for x in ReserveRangeRule().run(InMemoryContext(reserves=rows)) if "z_modificado" in x.evidence]
        self.assertEqual(z, [])
        # Control negativo: si se mezclaran en un solo grupo, el sistema sí marcaría atípicos.
        for r in rows:
            r["currency"] = None
        mixed = [x for x in ReserveRangeRule().run(InMemoryContext(reserves=rows)) if "z_modificado" in x.evidence]
        self.assertTrue(mixed)


class IngestionTest(unittest.TestCase):
    def test_validate_and_normalize(self):
        ok = {"payment_id": "1", "policy_number": "p1", "payer_id": "v-1", "amount": "1.250,5"[:0] + "1250,50", "currency": "usd",
              "method": "cash", "paid_at": "2026-09-01T10:00"}
        self.assertEqual(validate_row("payments", ok), [])
        n = normalize_row("payments", ok)
        self.assertEqual((n["amount"], n["currency"], n["method"], n["paid_at"], n["policy_number"]),
                         ("1250.50", "USD", "CASH", "2026-09-01", "P1"))
        bad = {**ok, "currency": "XXX", "method": "BITCOIN", "amount": "abc", "paid_at": "2026-02-31"}
        self.assertEqual(len(validate_row("payments", bad)), 4)
        self.assertIn("amount debe ser mayor que cero", validate_row("payments", {**ok, "amount": "0"}))

    def test_unknown_columns_are_dropped(self):
        row = {"claim_number": "S1", "policy_number": "P", "occurrence_date": "2026-01-01", "reported_date": "2026-01-02",
               "claimed_amount": "5", "currency": "VES", "x; DROP TABLE users": "1"}
        self.assertNotIn("x; DROP TABLE users", normalize_row("claims", row))

    def test_reconciliation_zero_tolerance(self):
        t = ControlTotals()
        for a in ("0.10", "0.20"):
            t.add({"amount": a, "currency": "USD", "id": a}, "amount")
        self.assertEqual(reconcile(t, 2, {"USD": Dec("0.30")}), [])
        self.assertTrue(reconcile(t, 2, {"USD": Dec("0.31")}))
        self.assertTrue(reconcile(t, 3, {"USD": Dec("0.30")}))
        self.assertTrue(reconcile(t, 2, {"USD": Dec("0.30"), "VES": Dec("5")}))

    def test_control_hash_is_order_independent(self):
        rows = [{"amount": str(i), "currency": "USD", "id": i} for i in range(5)]
        a, b = ControlTotals(), ControlTotals()
        for r in rows: a.add(r, "amount")
        for r in reversed(rows): b.add(r, "amount")
        self.assertEqual(a.hash_hex, b.hash_hex)
        b.add({"amount": "1", "currency": "USD", "id": 99}, "amount")
        self.assertNotEqual(a.hash_hex, b.hash_hex)


class LoggingRedactionTest(unittest.TestCase):
    def test_redacts_sensitive_data(self):
        out = redact('login ok user=a@b.com cédula V-12.345.678 token=abc123 Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig12345 {"password": "S3cr3t!"}')
        for leaked in ("a@b.com", "12.345.678", "abc123", "eyJhbGci", "S3cr3t"):
            self.assertNotIn(leaked, out)

    def test_filter_applies_to_records(self):
        rec = logging.LogRecord("x", logging.INFO, "f", 1, "pago de %s", ("J-12345678-9",), None)
        RedactingFilter().filter(rec)
        self.assertNotIn("12345678", rec.getMessage())


if __name__ == "__main__":
    unittest.main()
