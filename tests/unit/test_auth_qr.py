"""Pruebas de generación local del QR para el alta MFA."""
import base64
import unittest

from app.modules.auth.api import _qr_png_data_uri


class MfaQrTests(unittest.TestCase):
    def test_provisioning_uri_returns_png_data_uri(self):
        uri = (
            "otpauth://totp/SICAS:usuario-prueba"
            "?secret=JBSWY3DPEHPK3PXP&issuer=SICAS&digits=6&period=30"
        )
        result = _qr_png_data_uri(uri)

        self.assertTrue(result.startswith("data:image/png;base64,"))
        png = base64.b64decode(result.split(",", 1)[1], validate=True)
        self.assertTrue(png.startswith(bytes.fromhex("89504e470d0a1a0a")))
        self.assertGreater(len(png), 100)


if __name__ == "__main__":
    unittest.main()
