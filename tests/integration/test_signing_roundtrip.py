"""
Prueba de integración de firma PAdES. Se omite si pyHanko no está instalado.
Genera un certificado autofirmado de prueba, firma un dictamen y verifica integridad y manipulación.
Ejecutar: pip install -r requirements/base.txt && python -m unittest tests.integration.test_signing_roundtrip -v
"""
import datetime
import importlib.util
import io
import os
import tempfile
import unittest

HAS_PYHANKO = importlib.util.find_spec("pyhanko") is not None


@unittest.skipUnless(HAS_PYHANKO, "pyHanko no instalado")
class SigningRoundTrip(unittest.TestCase):
    def setUp(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import pkcs12
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Contralor de Prueba")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=30))
                .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
                .sign(key, hashes.SHA256()))
        self.tmp = tempfile.mkdtemp()
        self.p12 = os.path.join(self.tmp, "t.p12")
        with open(self.p12, "wb") as fh:
            fh.write(pkcs12.serialize_key_and_certificates(
                b"test", key, cert, None, serialization.BestAvailableEncryption(b"pw")))
        self.pass_file = os.path.join(self.tmp, "pw")
        with open(self.pass_file, "wb") as fh:
            fh.write(b"pw")

    def test_sign_and_detect_tampering(self):
        from app.modules.reporting.dictamen_pdf import build_dictamen_pdf
        from app.modules.reporting.signing import service, verify

        pdf = build_dictamen_pdf({"folio": "T-1", "kind": "DICTAMEN", "title": "t", "company": "c",
                                  "date": "2026-09-30", "findings": [], "conclusion": "ok", "body_sha256": "0" * 64})
        signer = service.load_signer({"SIGNING_MODE": "pkcs12", "SIGNING_PKCS12_PATH": self.p12,
                                      "SIGNING_PKCS12_PASSPHRASE_FILE": self.pass_file})
        signed = service.sign_pdf(pdf, signer, reason="Prueba", location="Caracas", signer_name="Contralor")
        res = verify.verify_pdf(signed.pdf_bytes, None)
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0]["intact"] and res[0]["valid"])
        self.assertFalse(res[0]["trusted"])             # autofirmado: sin raíz de confianza

        tampered = bytearray(signed.pdf_bytes)
        idx = tampered.find(b"Prueba")
        tampered[idx] = ord("X")
        res2 = verify.verify_pdf(bytes(tampered), None)
        self.assertFalse(res2[0]["intact"] and res2[0]["valid"])


if __name__ == "__main__":
    unittest.main()
