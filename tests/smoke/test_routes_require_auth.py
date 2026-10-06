"""
Prueba de humo de seguridad (se ejecuta en SU equipo, con las dependencias reales instaladas):
TODA ruta de la API, salvo las públicas indicadas, debe responder 401 sin sesión. Falla si alguien agrega
un endpoint sin protección. Se omite si faltan librerías o no hay Redis.
Requiere .env de desarrollo (python scripts/init_env.py).
"""
import importlib.util
import os
import re
import unittest
import uuid

PUBLIC = {  # (ruta, método): se permite responder sin sesión
    ("/", "GET"), ("/api/v1/health", "GET"), ("/api/v1/health/ready", "GET"), ("/api/v1/auth/login", "POST"), ("/api/v1/auth/password/change", "POST"),
    ("/api/v1/auth/mfa/enroll", "POST"), ("/api/v1/auth/mfa/confirm", "POST"), ("/api/v1/auth/mfa/verify", "POST"), ("/api/v1/auth/logout", "POST"),
}
_ARG = re.compile(r"<(?:(\w+)(?:\([^)]*\))?:)?(\w+)>")


def fill_path(rule: str) -> str:
    """Reemplaza <uuid:x> por un UUID, <int:x> por 1 y cualquier otro <x> por 'x'."""
    return _ARG.sub(lambda m: str(uuid.uuid4()) if m.group(1) == "uuid" else "1" if m.group(1) == "int" else "x", rule)


HAS_LIBS = all(importlib.util.find_spec(m) for m in ("flask_jwt_extended", "flask_sqlalchemy", "flask_limiter", "flask_talisman", "flask_cors", "celery", "redis"))


@unittest.skipUnless(HAS_LIBS, "Faltan las dependencias de la aplicación")
class RoutesRequireAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app.core.env import load_dotenv_file
        load_dotenv_file()
        os.environ.setdefault("SICAS_ENV", "dev")
        import redis
        try:
            redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0")).ping()
        except Exception:  # noqa: BLE001
            raise unittest.SkipTest("Redis no está disponible")
        from app import create_app
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def test_every_protected_route_returns_401_without_session(self):
        failures, checked = [], 0
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint == "static":
                continue
            path = fill_path(rule.rule)
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                if (rule.rule, method) in PUBLIC:
                    continue
                resp = self.client.open(path, method=method, json={} if method in ("POST", "PUT", "PATCH") else None)
                checked += 1
                if resp.status_code != 401:
                    failures.append(f"{method} {rule.rule} -> {resp.status_code}")
        self.assertGreater(checked, 60, "Se esperaban muchas rutas; revise el registro de blueprints")
        self.assertEqual(failures, [], "Rutas sin protección:\n" + "\n".join(failures))

    def test_security_headers_present(self):
        r = self.client.get("/api/v1/health")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src", r.headers.get("Content-Security-Policy", ""))
        self.assertEqual(r.headers.get("Cache-Control"), "no-store")


if __name__ == "__main__":
    unittest.main()
