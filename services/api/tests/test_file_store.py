"""Private local/S3 storage contract tests using synthetic object bytes."""

from __future__ import annotations

import base64
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.storage.file_store import PrivateFileStore
from app.storage.s3_file_store import S3FileStore


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}
        self.put_calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        if kwargs["Key"] in self.objects:
            raise ClientError(
                {
                    "Error": {"Code": "PreconditionFailed"},
                    "ResponseMetadata": {"HTTPStatusCode": 412},
                },
                "PutObject",
            )
        body = kwargs["Body"]
        self.objects[kwargs["Key"]] = {
            "Body": body,
            "ContentLength": len(body),
            "Metadata": kwargs["Metadata"],
        }

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == "synthetic-private-bucket"
        obj = self.objects[Key]
        return {"ContentLength": obj["ContentLength"], "Metadata": obj["Metadata"]}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == "synthetic-private-bucket"
        obj = self.objects[Key]
        return {
            "Body": BytesIO(obj["Body"]),
            "ContentLength": obj["ContentLength"],
            "Metadata": obj["Metadata"],
        }


class ConflictOnceS3(MemoryS3):
    def put_object(self, **kwargs: Any) -> None:
        if not self.put_calls:
            self.put_calls.append(kwargs)
            raise ClientError(
                {
                    "Error": {"Code": "ConditionalRequestConflict"},
                    "ResponseMetadata": {"HTTPStatusCode": 409},
                },
                "PutObject",
            )
        super().put_object(**kwargs)


def test_local_store_bounds_hashes_and_rejects_tampering(tmp_path: Path) -> None:
    store = PrivateFileStore(tmp_path / "private", max_object_bytes=4)
    key, digest = store.put(b"safe")
    assert digest == hashlib.sha256(b"safe").hexdigest()
    assert store.read(key) == b"safe"
    with pytest.raises(ValueError, match="write limit"):
        store.put(b"too large")
    with pytest.raises(ValueError, match="read limit"):
        store.read(key, max_bytes=3)

    (tmp_path / "private" / key).write_bytes(b"evil")
    with pytest.raises(OSError, match="hash mismatch"):
        store.read(key)
    with pytest.raises(ValueError, match="Invalid private file key"):
        store.read("../outside")


def test_local_store_bounds_existing_content_addressed_object_hash(
    tmp_path: Path,
) -> None:
    store = PrivateFileStore(tmp_path / "private", max_object_bytes=4)
    key, _ = store.put(b"safe")
    (tmp_path / "private" / key).write_bytes(b"oversized existing object")
    with pytest.raises(ValueError, match="write limit"):
        store.put(b"safe")


def test_s3_store_closes_streaming_body_when_read_raises() -> None:
    class BrokenBody:
        closed = False

        def read(self, _size: int) -> bytes:
            raise OSError("synthetic stream failure")

        def close(self) -> None:
            self.closed = True

    class BrokenReadS3(MemoryS3):
        def __init__(self) -> None:
            super().__init__()
            self.body = BrokenBody()

        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            return {
                "Body": self.body,
                "ContentLength": 1,
                "Metadata": {"sha256": Key.removesuffix(".blob")},
            }

    client = BrokenReadS3()
    store = S3FileStore("synthetic-private-bucket", "us-east-1", client=client)
    key = f"{hashlib.sha256(b'x').hexdigest()}.blob"
    with pytest.raises(OSError, match="synthetic stream failure"):
        store.read(key)
    assert client.body.closed is True


def test_s3_store_uses_conditional_encrypted_content_addressed_objects() -> None:
    client = MemoryS3()
    store = S3FileStore(
        "synthetic-private-bucket", "us-east-1", client=client, max_object_bytes=19
    )
    key, digest = store.put(b"synthetic statement")
    assert key == f"{digest}.blob"
    request = client.put_calls[0]
    assert request["IfNoneMatch"] == "*"
    assert request["ChecksumSHA256"] == base64.b64encode(bytes.fromhex(digest)).decode(
        "ascii"
    )
    assert request["ServerSideEncryption"] == "AES256"
    assert request["ContentType"] == "application/octet-stream"
    assert store.put(b"synthetic statement") == (key, digest)
    assert len(client.put_calls) == 2
    assert store.read(key) == b"synthetic statement"
    with pytest.raises(ValueError, match="write limit"):
        store.put(b"this statement is too large")
    with pytest.raises(ValueError, match="read limit"):
        store.read(key, max_bytes=5)


def test_s3_store_rejects_invalid_keys_and_object_identity_mismatch() -> None:
    client = MemoryS3()
    store = S3FileStore("synthetic-private-bucket", "us-east-1", client=client)
    with pytest.raises(ValueError, match="Invalid private file key"):
        store.read("folder/statement.pdf")
    key, _ = store.put(b"synthetic")
    client.objects[key]["Metadata"] = {"sha256": "0" * 64}
    with pytest.raises(OSError, match="hash mismatch"):
        store.read(key)


def test_s3_kms_selection_is_explicit() -> None:
    client = MemoryS3()
    store = S3FileStore(
        "synthetic-private-bucket",
        "us-east-1",
        client=client,
        kms_key_id="arn:aws:kms:us-east-1:111122223333:key/synthetic",
    )
    store.put(b"synthetic")
    request = client.put_calls[0]
    assert request["ServerSideEncryption"] == "aws:kms"
    assert request["SSEKMSKeyId"].endswith("key/synthetic")


def test_s3_store_retries_one_conditional_conflict() -> None:
    client = ConflictOnceS3()
    store = S3FileStore("synthetic-private-bucket", "us-east-1", client=client)
    key, digest = store.put(b"retry-safe synthetic")
    assert len(client.put_calls) == 2
    assert store.read(key) == b"retry-safe synthetic"
    assert key == f"{digest}.blob"
