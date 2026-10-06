import unittest
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.integrity.checkpoint import Checkpoint, check_against_log, create_checkpoint, verify_checkpoint

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


class CheckpointTest(unittest.TestCase):
    def setUp(self):
        self.priv = Ed25519PrivateKey.generate()
        self.cp = create_checkpoint(self.priv, "cp1", 1500, "ab" * 32, NOW)

    def test_valid_signature(self):
        self.assertTrue(verify_checkpoint(self.priv.public_key(), self.cp))

    def test_tampered_fields_invalidate_signature(self):
        for changed in (Checkpoint(NOW, 1499, "ab" * 32, "cp1", self.cp.signature),
                        Checkpoint(NOW, 1500, "cd" * 32, "cp1", self.cp.signature),
                        Checkpoint(NOW, 1500, "ab" * 32, "cp2", self.cp.signature)):
            self.assertFalse(verify_checkpoint(self.priv.public_key(), changed))

    def test_foreign_key_rejected(self):
        self.assertFalse(verify_checkpoint(Ed25519PrivateKey.generate().public_key(), self.cp))

    def test_detects_deleted_tail_and_altered_row(self):
        self.assertIsNone(check_against_log(self.cp, "ab" * 32))
        self.assertIn("borrado", check_against_log(self.cp, None))
        self.assertIn("alteración", check_against_log(self.cp, "ff" * 32))


if __name__ == "__main__":
    unittest.main()
