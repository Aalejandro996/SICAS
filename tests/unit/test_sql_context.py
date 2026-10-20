import unittest

from app.modules.audit_engine.context import SqlContext


class FakeRow:
    def __init__(self, values):
        self._mapping = values


class FakeConnection:
    def __init__(self):
        self.sql = ""
        self.params = None

    def execution_options(self, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, params):
        self.sql = str(statement)
        self.params = params
        return iter([
            FakeRow({
                "_id": 42,
                "reserve_type": "CLAIM",
                "branch": "AUTO",
                "policy_number": "POL-TEST",
                "claim_number": "SIN-TEST",
                "period": "2026-09-01",
                "amount": 1200,
                "sum_insured": 50000,
                "currency": "USD",
            })
        ])


class FakeEngine:
    def __init__(self):
        self.connection = FakeConnection()

    def connect(self):
        return self.connection


class SqlContextTests(unittest.TestCase):
    def test_reserves_selects_the_identifier_required_by_rules(self):
        engine = FakeEngine()
        job_id = "00000000-0000-0000-0000-000000000001"

        rows = list(SqlContext(engine, job_id=job_id).reserves())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["_id"], 42)
        self.assertIn("SELECT id AS _id, reserve_type", engine.connection.sql)
        self.assertEqual(engine.connection.params["job_id"], job_id)
        self.assertIn(
            "job_id = CAST(:job_id AS uuid)",
            engine.connection.sql,
        )


    def test_claim_lookup_prefers_policy_valid_on_occurrence_date(self):
        engine = FakeEngine()
        job_id = "00000000-0000-0000-0000-000000000002"

        list(SqlContext(engine, job_id=job_id).claims())

        sql = engine.connection.sql
        self.assertIn("LEFT JOIN LATERAL", sql)
        self.assertIn("x.policy_number = c.policy_number", sql)
        self.assertIn(
            "WHEN c.occurrence_date BETWEEN x.start_date AND x.end_date",
            sql,
        )
        self.assertIn("x.id DESC LIMIT 1", sql)
        self.assertEqual(engine.connection.params["job_id"], job_id)


if __name__ == "__main__":
    unittest.main()
