"""
Archivos de auditoría: evidencias y PDF firmados.
  - Producción: S3/MinIO (bucket S3_ENGAGEMENT_BUCKET), cifrado del lado servidor; para los PDF firmados, activar Object Lock.
  - Desarrollo (SICAS_ENV=dev y sin bucket): carpeta local data/engagement.
Los objetos no se sobrescriben.
"""
import os
import pathlib

LOCAL = pathlib.Path(__file__).resolve().parents[3] / "data" / "engagement"


def _local() -> bool:
    return os.environ.get("SICAS_ENV", "prod").lower() == "dev" and not os.environ.get("S3_ENGAGEMENT_BUCKET")


def _s3():
    import boto3
    return boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None)


def put(key: str, data: bytes) -> None:
    if _local():
        path = (LOCAL / key).resolve()
        if LOCAL.resolve() not in path.parents:
            raise ValueError("Ruta inválida")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError("El objeto ya existe")
        path.write_bytes(data)
        return
    _s3().put_object(
        Bucket=os.environ["S3_ENGAGEMENT_BUCKET"],
        Key=key,
        Body=data,
        IfNoneMatch="*",
    )


def get(key: str) -> bytes:
    if _local():
        path = (LOCAL / key).resolve()
        if LOCAL.resolve() not in path.parents:
            raise ValueError("Ruta inválida")
        return path.read_bytes()
    return _s3().get_object(Bucket=os.environ["S3_ENGAGEMENT_BUCKET"], Key=key)["Body"].read()
