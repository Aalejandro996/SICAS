import os
from datetime import timedelta

ENV = os.environ.get("SICAS_ENV", "prod").lower()          # "dev" relaja SOLO HTTPS/cookies seguras y da valores locales


def _env(name: str, dev_default: str | None = None) -> str:
    value = os.environ.get(name)
    if value:
        return value
    if ENV == "dev" and dev_default is not None:
        return dev_default
    raise RuntimeError(f"Variable de entorno obligatoria no definida: {name}")

def normalize_sqlalchemy_url(url: str) -> str:
    """Admite las URLs PostgreSQL habituales de proveedores gestionados."""
    url = url.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class BaseConfig:
    ENV = ENV
    SECRET_KEY = _env("SECRET_KEY")
    JWT_SECRET_KEY = _env("JWT_SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = normalize_sqlalchemy_url(_env("DATABASE_URL", "postgresql+psycopg://app_rw:dev@localhost:5432/contraloria"))
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_size": int(os.environ.get("DB_POOL_SIZE", "20")), "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10"))}

    # HTTPS y cookies seguras: obligatorios fuera de desarrollo
    FORCE_HTTPS = ENV != "dev"
    JWT_COOKIE_SECURE = ENV != "dev"
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_COOKIE_SAMESITE = "Strict"
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_REFRESH_COOKIE_PATH = "/api/v1/auth/"
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=10)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(hours=8)

    RATELIMIT_STORAGE_URI = _env("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL = _env("CELERY_BROKER_URL", "redis://localhost:6379/1")
    CELERY_RESULT_BACKEND = _env("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
    CELERY_EAGER = os.environ.get("SICAS_CELERY_EAGER", "0") == "1"      # solo desarrollo
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024
    CORS_ORIGINS = _env("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",")

    MAX_FAILED_LOGINS = 5
    LOCKOUT_MINUTES = 30
    CHALLENGE_TTL_SECONDS = 300
    STEP_UP_MAX_AGE_SECONDS = 300      # reautenticación MFA reciente para firmar y acciones críticas

    COMPANY_NAME = os.environ.get("SICAS_COMPANY", "Aseguradora")

    # Firma electrónica
    SIGNING_MODE = os.environ.get("SIGNING_MODE", "pkcs12")
    SIGNING_PKCS12_PATH = os.environ.get("SIGNING_PKCS12_PATH")
    SIGNING_PKCS12_PASSPHRASE_FILE = os.environ.get("SIGNING_PKCS12_PASSPHRASE_FILE")
    SIGNING_PKCS12_PATH_GERENTE = os.environ.get("SIGNING_PKCS12_PATH_GERENTE")
    SIGNING_PKCS12_PASSPHRASE_FILE_GERENTE = os.environ.get("SIGNING_PKCS12_PASSPHRASE_FILE_GERENTE")
    SIGNING_TRUST_ROOTS_PEM = os.environ.get("SIGNING_TRUST_ROOTS_PEM")
    TSA_URL = os.environ.get("TSA_URL")
