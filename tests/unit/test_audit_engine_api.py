import unittest
from types import SimpleNamespace

from app.modules.audit_engine.api import _job_status_error, _manual_run_scope


class ManualRunScopeTests(unittest.TestCase):
    def test_empty_payload_is_not_an_implicit_global_run(self):
        job, error = _manual_run_scope({})
        self.assertIsNone(job)
        self.assertEqual(error[1], 400)

    def test_global_scope_must_be_explicit(self):
        job, error = _manual_run_scope({"scope": "GLOBAL"})
        self.assertIsNone(job)
        self.assertIsNone(error)

    def test_global_scope_rejects_a_job_id(self):
        job, error = _manual_run_scope({
            "scope": "GLOBAL",
            "job_id": "00000000-0000-0000-0000-000000000001",
        })
        self.assertIsNone(job)
        self.assertEqual(error[1], 400)

    def test_job_scope_requires_job_id(self):
        job, error = _manual_run_scope({"scope": "JOB"})
        self.assertIsNone(job)
        self.assertEqual(error[1], 400)

    def test_job_scope_normalizes_uuid(self):
        job, error = _manual_run_scope({
            "scope": "JOB",
            "job_id": "00000000-0000-0000-0000-000000000001",
        })
        self.assertEqual(job, "00000000-0000-0000-0000-000000000001")
        self.assertIsNone(error)

    def test_job_scope_rejects_invalid_uuid(self):
        job, error = _manual_run_scope({"scope": "JOB", "job_id": "not-a-uuid"})
        self.assertIsNone(job)
        self.assertEqual(error[1], 400)

    def test_unknown_scope_is_rejected(self):
        job, error = _manual_run_scope({"scope": "BATCH"})
        self.assertIsNone(job)
        self.assertEqual(error[1], 400)

    def test_missing_job_is_not_found(self):
        self.assertEqual(_job_status_error(None), ("La carga no existe", 404))

    def test_incomplete_job_is_rejected(self):
        error = _job_status_error(SimpleNamespace(status="PROCESSING"))
        self.assertEqual(error[1], 409)

    def test_completed_job_is_accepted(self):
        self.assertIsNone(_job_status_error(SimpleNamespace(status="COMPLETED")))


if __name__ == "__main__":
    unittest.main()
