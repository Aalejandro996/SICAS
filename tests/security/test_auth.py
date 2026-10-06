import hashlib
import os
import unittest
from datetime import datetime, timedelta, timezone

from app.core.security.crypto import CryptoError, KeyRing, blind_index
from app.modules.auth import lockout, totp
from app.modules.auth.password import validate_password
from app.modules.auth.refresh import InMemoryRefreshStore, RefreshError, RefreshService, ReuseDetected
from app.modules.auth.service import AuthError, AuthService, User

T0 = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)


class FastHasher:                                    # scrypt estándar, parámetros bajos solo para pruebas
    calls = 0

    def hash(self, p):
        salt = os.urandom(8)
        return salt.hex() + "$" + hashlib.scrypt(p.encode(), salt=salt, n=2 ** 8, r=8, p=1).hex()

    def verify(self, h, p):
        FastHasher.calls += 1
        s, d = h.split("$")
        return hashlib.scrypt(p.encode(), salt=bytes.fromhex(s), n=2 ** 8, r=8, p=1).hex() == d

    def needs_rehash(self, h): return False


class FakeRepo:
    def __init__(self, user): self.u, self.hist, self.audit_log = user, [], []
    def find_by_username(self, name): return self.u if self.u and name == self.u.username else None
    def save_state(self, uid, st): self.u.state = st
    def save_mfa(self, uid, enc, confirmed): self.u.mfa_secret_enc, self.u.mfa_confirmed = enc, confirmed
    def set_mfa_last_step(self, uid, step): self.u.mfa_last_step = step
    def set_password(self, uid, h): self.u.password_hash = h
    def password_history(self, uid, n): return self.hist[-n:]
    def add_password_history(self, uid, h): self.hist.append(h)


def build(clock):
    h = FastHasher()
    user = User("u1", "jperez", "jperez@x.com", "Juan Pérez", h.hash("Clave-Segura#2026"))
    repo = FakeRepo(user)
    ring = KeyRing({"k1": os.urandom(32)}, "k1")
    svc = AuthService(repo, h, ring, lambda *a, **k: repo.audit_log.append((a, k)), clock=clock)
    return svc, repo, user, ring


class LoginTest(unittest.TestCase):
    def setUp(self):
        self.now = T0
        self.svc, self.repo, self.user, self.ring = build(lambda: self.now)

    def test_generic_error_for_unknown_user_and_runs_hash(self):
        before = FastHasher.calls
        with self.assertRaises(AuthError) as c:
            self.svc.verify_password_step("noexiste", "x")
        self.assertEqual(c.exception.code, "INVALID_CREDENTIALS")
        self.assertGreater(FastHasher.calls, before)       # se ejecutó un hash: tiempo comparable

    def test_progressive_lockout_and_locked_even_with_correct_password(self):
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.svc.verify_password_step("jperez", "mala")
        self.assertTrue(lockout.is_locked(self.user.state, self.now))
        with self.assertRaises(AuthError) as c:
            self.svc.verify_password_step("jperez", "Clave-Segura#2026")
        self.assertEqual(c.exception.code, "LOCKED")
        self.now += timedelta(minutes=31)
        self.assertEqual(self.svc.verify_password_step("jperez", "Clave-Segura#2026").id, "u1")
        # segundo bloqueo dura el doble
        s = lockout.LoginState(0, None, 1)
        for _ in range(5):
            s = lockout.register_failure(s, T0)
        self.assertEqual(s.locked_until - T0, timedelta(minutes=60))

    def test_mfa_enroll_verify_and_replay_rejected(self):
        secret, uri = self.svc.begin_mfa_enrollment(self.user)
        self.assertIn("otpauth://totp/SICAS", uri)
        code = totp.totp_at(secret, self.now.timestamp())
        self.svc.confirm_mfa_enrollment(self.user, code)
        self.now += timedelta(seconds=60)
        code2 = totp.totp_at(secret, self.now.timestamp())
        self.svc.verify_mfa_step(self.user, code2)
        with self.assertRaises(AuthError):                  # mismo código otra vez = replay
            self.svc.verify_mfa_step(self.user, code2)

    def test_wrong_mfa_counts_toward_lockout(self):
        secret, _ = self.svc.begin_mfa_enrollment(self.user)
        self.svc.confirm_mfa_enrollment(self.user, totp.totp_at(secret, self.now.timestamp()))
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.svc.verify_mfa_step(self.user, "000000")
        self.assertTrue(lockout.is_locked(self.user.state, self.now))

    def test_secret_is_encrypted_and_bound_to_user(self):
        secret, _ = self.svc.begin_mfa_enrollment(self.user)
        self.assertNotIn(secret, self.user.mfa_secret_enc)
        with self.assertRaises(CryptoError):
            self.ring.decrypt(self.user.mfa_secret_enc, aad=b"otro-usuario")

    def test_password_change_policy_and_history(self):
        with self.assertRaises(AuthError) as c:
            self.svc.change_password(self.user, "Clave-Segura#2026", "corta")
        self.assertEqual(c.exception.code, "WEAK_PASSWORD")
        self.svc.change_password(self.user, "Clave-Segura#2026", "Otra-Clave#Muy2027")
        with self.assertRaises(AuthError) as c:
            self.svc.change_password(self.user, "Otra-Clave#Muy2027", "Clave-Segura#2026")
        self.assertEqual(c.exception.code, "PASSWORD_REUSED")


class TotpVectorsTest(unittest.TestCase):
    SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"             # "12345678901234567890" (RFC 6238)

    def test_rfc6238_vectors(self):
        self.assertEqual(totp.totp_at(self.SECRET, 59, 8), "94287082")
        self.assertEqual(totp.totp_at(self.SECRET, 1111111109, 8), "07081804")

    def test_window_and_format(self):
        self.assertIsNotNone(totp.verify(self.SECRET, totp.totp_at(self.SECRET, 1000), now=1000 + 30))
        self.assertIsNone(totp.verify(self.SECRET, totp.totp_at(self.SECRET, 1000), now=1000 + 120))
        self.assertIsNone(totp.verify(self.SECRET, "abcdef", now=1000))


class PasswordPolicyTest(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(validate_password("abc"))
        self.assertTrue(validate_password("soloMinusculas1234"[:11]))
        self.assertTrue(validate_password("Jperez-Clave#2026", username="jperez"))
        self.assertTrue(validate_password("Aaaaaaa#12345"))
        self.assertEqual(validate_password("Zorro&Luna#Rio88", username="jperez"), [])


class RefreshRotationTest(unittest.TestCase):
    def test_rotation_and_reuse_revokes_family(self):
        svc = RefreshService(InMemoryRefreshStore())
        r1 = svc.start_session("u1", T0)
        r2 = svc.rotate(r1.jti, T0)
        self.assertEqual(r1.family_id, r2.family_id)
        with self.assertRaises(ReuseDetected):               # r1 ya se usó: robo
            svc.rotate(r1.jti, T0)
        with self.assertRaises(RefreshError):                # y r2 (legítimo) también quedó revocado
            svc.rotate(r2.jti, T0)

    def test_expired_and_logout(self):
        svc = RefreshService(InMemoryRefreshStore(), ttl=timedelta(hours=1))
        r = svc.start_session("u1", T0)
        with self.assertRaises(RefreshError):
            svc.rotate(r.jti, T0 + timedelta(hours=2))
        r = svc.start_session("u1", T0)
        svc.logout(r.jti)
        with self.assertRaises(RefreshError):
            svc.rotate(r.jti, T0)


class CryptoTest(unittest.TestCase):
    def test_rotation_tamper_and_blind_index(self):
        k1, k2 = os.urandom(32), os.urandom(32)
        old = KeyRing({"k1": k1}, "k1").encrypt(b"V-12345678")
        ring = KeyRing({"k1": k1, "k2": k2}, "k2")
        self.assertEqual(ring.decrypt(old), b"V-12345678")
        self.assertTrue(ring.needs_rotation(old))
        with self.assertRaises(CryptoError):
            ring.decrypt(old[:-2] + "AA")
        self.assertEqual(blind_index("v-12.345.678", k1), blind_index("V12345678", k1))
        self.assertNotEqual(blind_index("V12345678", k1), blind_index("V12345678", k2))


if __name__ == "__main__":
    unittest.main()
