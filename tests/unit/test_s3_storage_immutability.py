import io

import boto3

from app.modules.ingestion import storage as ingestion_storage
from app.modules.engagement import storage as engagement_storage
from app.modules.reporting import storage as reporting_storage


class FakeS3:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"ETag": '"test"'}


def assert_conditional_kms_write(client, bucket, key):
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Bucket"] == bucket
    assert call["Key"] == key
    assert call["ServerSideEncryption"] == "aws:kms"
    assert call["IfNoneMatch"] == "*"


def test_ingestion_write_is_conditional(monkeypatch):
    monkeypatch.setenv("SICAS_ENV", "prod")
    monkeypatch.setenv("S3_BUCKET", "test-ingestion")
    client = FakeS3()
    monkeypatch.setattr(ingestion_storage, "_client", lambda: client)

    stream = io.BytesIO(b"id,value\n1,2\n")
    key = ingestion_storage.save_encrypted(stream, "job-test")

    assert key == "ingestion/job-test.csv"
    assert client.calls[0]["Body"] is stream
    assert_conditional_kms_write(client, "test-ingestion", key)


def test_engagement_write_is_conditional(monkeypatch):
    monkeypatch.setenv("SICAS_ENV", "prod")
    monkeypatch.setenv("S3_ENGAGEMENT_BUCKET", "test-engagement")
    client = FakeS3()
    monkeypatch.setattr(engagement_storage, "_s3", lambda: client)

    engagement_storage.put("audit/evidence.pdf", b"pdf")

    assert_conditional_kms_write(
        client, "test-engagement", "audit/evidence.pdf"
    )


def test_signed_report_write_is_conditional(monkeypatch):
    monkeypatch.setenv("SICAS_ENV", "prod")
    monkeypatch.setenv("S3_SIGNED_BUCKET", "test-signed")
    client = FakeS3()
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: client)

    reporting_storage.put_signed("audit/report.pdf", b"signed pdf")

    assert_conditional_kms_write(
        client, "test-signed", "audit/report.pdf"
    )
