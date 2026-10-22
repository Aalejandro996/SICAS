"""
Almacenamiento de PDFs firmados.
  - Producción: S3/MinIO con Object Lock (WORM) en el bucket indicado por S3_SIGNED_BUCKET.
  - Desarrollo (SICAS_ENV=dev y sin S3_SIGNED_BUCKET): carpeta local data/signed.
"""
import os
import pathlib

LOCAL = pathlib.Path(__file__).resolve().parents[3] / "data" / "signed"


def _dev_local() -> bool:
    return os.environ.get("SICAS_ENV", "prod").lower() == "dev" and not os.environ.get("S3_SIGNED_BUCKET")


def put_signed(key: str, data: bytes) -> None:
    if _dev_local():
        path = LOCAL / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError("Un documento firmado no se sobrescribe")
        path.write_bytes(data)
        return
    import boto3
    boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None).put_object(
        Bucket=os.environ["S3_SIGNED_BUCKET"],
        Key=key,
        Body=data,
        IfNoneMatch="*",
    )


def get_signed(key: str) -> bytes:
    if _dev_local():
        return (LOCAL / key).read_bytes()
    import boto3
    return boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None).get_object(
        Bucket=os.environ["S3_SIGNED_BUCKET"], Key=key)["Body"].read()
