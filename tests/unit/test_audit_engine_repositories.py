import unittest
from pathlib import Path
from types import SimpleNamespace

from app.modules.audit_engine.models import Finding, Severity
from app.modules.audit_engine.repositories import save_findings


class FakeResult:
    def __init__(self, row=None, rowcount=0):
        self._row = row
        self.rowcount = rowcount

    def first(self):
        return self._row


class FakeSession:
    def __init__(self):
        self.findings = {}
        self.finding_status = {}
        self.finding_closed_by = {}
        self.finding_closed_reason = {}
        self.occurrences = {}
        self.next_id = 1

    def execute(self, statement, params=None):
        sql = str(statement).lstrip()
        params = params or {}

        if sql.startswith("INSERT INTO engine.findings"):
            fingerprint = params["fp"]
            if fingerprint in self.findings:
                return FakeResult()

            fid = self.next_id
            self.next_id += 1
            self.findings[fingerprint] = fid
            self.finding_status[fid] = "OPEN"
            self.finding_closed_by[fid] = None
            self.finding_closed_reason[fid] = None
            return FakeResult(SimpleNamespace(id=fid), 1)

        if sql.startswith("SELECT id, status FROM engine.findings"):
            fid = self.findings.get(params["fp"])
            row = (
                SimpleNamespace(id=fid, status=self.finding_status[fid])
                if fid is not None else None
            )
            return FakeResult(row)

        if sql.startswith("UPDATE engine.findings"):
            fid = params["id"]
            if self.finding_status[fid] == "CLOSED_RESOLVED":
                self.finding_status[fid] = "OPEN"
                self.finding_closed_by[fid] = None
                self.finding_closed_reason[fid] = None
            return FakeResult(rowcount=1)

        if sql.startswith("INSERT INTO engine.finding_occurrences"):
            key = (params["run"], params["fid"])
            if key not in self.occurrences:
                self.occurrences[key] = dict(params)
                return FakeResult(rowcount=1)
            return FakeResult(rowcount=0)

        raise AssertionError(f"SQL inesperado en FakeSession: {sql}")


class SaveFindingsTests(unittest.TestCase):
    def make_finding(self):
        return Finding(
            rule_code="TEST-RULE",
            severity=Severity.HIGH,
            entity_type="claim",
            entity_id="CLAIM-1",
            score=80,
            message="Hallazgo de prueba",
            evidence={"amount": 123},
            identity_facts={"case": "stable"},
        )

    def test_repeat_is_recorded_without_duplicating_master_finding(self):
        session = FakeSession()
        finding = self.make_finding()

        self.assertEqual(save_findings(session, "run-1", [finding]), 1)
        self.assertEqual(save_findings(session, "run-2", [finding]), 0)

        self.assertEqual(len(session.findings), 1)
        self.assertEqual(len(session.occurrences), 2)
        self.assertTrue(session.occurrences[("run-1", 1)]["new"])
        self.assertFalse(session.occurrences[("run-2", 1)]["new"])

    def test_same_run_does_not_duplicate_occurrence(self):
        session = FakeSession()
        finding = self.make_finding()

        save_findings(session, "run-1", [finding])
        save_findings(session, "run-1", [finding])

        self.assertEqual(len(session.findings), 1)
        self.assertEqual(len(session.occurrences), 1)
        self.assertTrue(session.occurrences[("run-1", 1)]["new"])

    def test_resolved_finding_reopens_and_becomes_alertable(self):
        session = FakeSession()
        finding = self.make_finding()

        save_findings(session, "run-1", [finding])
        fid = session.findings[finding.fingerprint]
        session.finding_status[fid] = "CLOSED_RESOLVED"
        session.finding_closed_by[fid] = "auditor-id"
        session.finding_closed_reason[fid] = "Se corrigió el problema"

        self.assertEqual(save_findings(session, "run-2", [finding]), 0)
        self.assertEqual(session.finding_status[fid], "OPEN")
        self.assertIsNone(session.finding_closed_by[fid])
        self.assertIsNone(session.finding_closed_reason[fid])
        self.assertTrue(session.occurrences[("run-2", fid)]["new"])
        self.assertEqual(len(session.findings), 1)

    def test_false_positive_remains_closed_on_same_fingerprint(self):
        session = FakeSession()
        finding = self.make_finding()

        save_findings(session, "run-1", [finding])
        fid = session.findings[finding.fingerprint]
        session.finding_status[fid] = "CLOSED_FP"
        session.finding_closed_reason[fid] = "Falso positivo confirmado"

        save_findings(session, "run-2", [finding])

        self.assertEqual(session.finding_status[fid], "CLOSED_FP")
        self.assertFalse(session.occurrences[("run-2", fid)]["new"])


class FindingOccurrenceMigrationTests(unittest.TestCase):
    def test_migration_backfills_existing_findings(self):
        root = Path(__file__).resolve().parents[2]
        sql = (root / "sql/023_engine_finding_occurrences.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("INSERT INTO engine.finding_occurrences", sql)
        self.assertIn("FROM engine.findings f", sql)
        self.assertIn("f.created_at", sql)
        self.assertIn("f.evidence", sql)
        self.assertIn("ON CONFLICT (run_id, finding_id) DO NOTHING", sql)


if __name__ == "__main__":
    unittest.main()
