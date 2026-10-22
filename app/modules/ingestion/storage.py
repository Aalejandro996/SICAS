"""
Almacenamiento de archivos cargados.
  - Producción: S3/MinIO con cifrado del lado servidor (S3_BUCKET obligatorio).
  - Desarrollo (SICAS_ENV=dev y sin S3_BUCKET): carpeta local data/uploads, SIN cifrar. Nunca usar con datos reales.
"""
import io
import os
import pathlib
from contextlib import contextmanager

LOCAL_DIR = pathlib.Path(__file__).resolve().parents[3] / "data" / "uploads"


def _local_allowed() -> bool:
    return os.environ.get("SICAS_ENV", "prod").lower() == "dev" and not os.environ.get("S3_BUCKET")


def _client():
    import boto3
    return boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None)


def save_encrypted(stream, job_id) -> str:
    if _local_allowed():
        LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        path = LOCAL_DIR / f"{job_id}.csv"
        with open(path, "wb") as fh:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                fh.write(chunk)
        return f"local:{job_id}.csv"
    key = f"ingestion/{job_id}.csv"
    _client().put_object(
        Bucket=os.environ["S3_BUCKET"],
        Key=key,
        Body=stream,
        ServerSideEncryption="aws:kms",
        IfNoneMatch="*",
    )
    return key


@contextmanager
def open_stream(object_key: str):
    if object_key.startswith("local:"):
        if not _local_allowed():
            raise PermissionError("Almacenamiento local no permitido fuera de desarrollo")
        with open(LOCAL_DIR / object_key[6:], "rb") as fh:
            yield fh
        return
    body = _client().get_object(Bucket=os.environ["S3_BUCKET"], Key=object_key)["Body"]
    try:
        yield io.BufferedReader(body._raw_stream)  # noqa: SLF001
    finally:
        body.close()
