"""
Crea DOS certificados de firma AUTOFIRMADOS solo para DESARROLLO (Contralor y Gerente de Control Interno) y los
configura en .env, para poder probar el flujo de firma del informe final. NO tienen validez legal: en producción
cada firmante usa un certificado de un proveedor acreditado ante SUSCERTE, custodiado en HSM, y una TSA reconocida
(ver docs/FIRMA_SELLADO.md).
Uso:  python scripts/init_dev_signing.py      y luego reinicie la aplicación.
"""
import datetime
import os
import pathlib
import secrets

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEC = ROOT / "secrets"
SEC.mkdir(mode=0o700, exist_ok=True)
now = datetime.datetime.now(datetime.timezone.utc)


def make(cn: str, stem: str) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{cn} (DESARROLLO - SIN VALIDEZ LEGAL)"), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SICAS desarrollo")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True, key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         key_cert_sign=False, crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    passphrase = secrets.token_urlsafe(24)
    (SEC / f"{stem}.p12").write_bytes(pkcs12.serialize_key_and_certificates(stem.encode(), key, cert, None, serialization.BestAvailableEncryption(passphrase.encode())))
    (SEC / f"{stem}.pass").write_text(passphrase)
    for ext in ("p12", "pass"):
        os.chmod(SEC / f"{stem}.{ext}", 0o600)
    return cert.public_bytes(serialization.Encoding.PEM)


roots = make("Contralor SICAS", "firma_dev") + make("Gerente SICAS", "firma_dev_gerente")
(SEC / "firma_dev_raiz.pem").write_bytes(roots)

env = ROOT / ".env"
current = env.read_text() if env.exists() else ""
drop = ("SIGNING_MODE=", "SIGNING_PKCS12_PATH=", "SIGNING_PKCS12_PASSPHRASE_FILE=", "SIGNING_PKCS12_PATH_GERENTE=", "SIGNING_PKCS12_PASSPHRASE_FILE_GERENTE=", "SIGNING_TRUST_ROOTS_PEM=")
lines = [l for l in current.splitlines() if not l.startswith(drop)]
lines += ["SIGNING_MODE=pkcs12", f"SIGNING_PKCS12_PATH={SEC / 'firma_dev.p12'}", f"SIGNING_PKCS12_PASSPHRASE_FILE={SEC / 'firma_dev.pass'}",
          f"SIGNING_PKCS12_PATH_GERENTE={SEC / 'firma_dev_gerente.p12'}", f"SIGNING_PKCS12_PASSPHRASE_FILE_GERENTE={SEC / 'firma_dev_gerente.pass'}",
          f"SIGNING_TRUST_ROOTS_PEM={SEC / 'firma_dev_raiz.pem'}"]
env.write_text("\n".join(lines) + "\n")
print("Certificados de DESARROLLO creados (Contralor y Gerente) y configurados en .env. Sin sello de tiempo (no hay TSA).\nReinicie la aplicación para aplicar.")
