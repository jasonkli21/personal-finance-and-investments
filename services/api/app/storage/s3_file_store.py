"""Private, content-addressed S3 storage using the workload IAM role."""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, cast


class S3FileStore:
    """Store source bytes in a private bucket without issuing public URLs."""

    _KEY = re.compile(r"^[0-9a-f]{64}\.blob$")

    def __init__(
        self,
        bucket: str,
        region: str,
        *,
        kms_key_id: str | None = None,
        max_object_bytes: int = 20_000_000,
        client: Any | None = None,
    ) -> None:
        if not bucket or not region:
            raise ValueError("Private S3 bucket and AWS region are required")
        self.bucket = bucket
        self.max_object_bytes = max_object_bytes
        self._kms_key_id = kms_key_id
        if client is None:
            import boto3  # type: ignore[import-untyped]

            client = boto3.client("s3", region_name=region)
        self._client = client

    def put(self, content: bytes) -> tuple[str, str]:
        if len(content) > self.max_object_bytes:
            raise ValueError("Private file exceeds the configured write limit")
        digest = hashlib.sha256(content).hexdigest()
        key = f"{digest}.blob"
        encrypted = self._kms_key_id is not None
        request = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": content,
            "ContentLength": len(content),
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(digest)).decode("ascii"),
            "ContentType": "application/octet-stream",
            "Metadata": {"sha256": digest},
            "ServerSideEncryption": "aws:kms" if encrypted else "AES256",
            **({"SSEKMSKeyId": self._kms_key_id} if encrypted else {}),
            "IfNoneMatch": "*",
        }
        for attempt in range(2):
            try:
                self._client.put_object(**request)
                break
            except Exception as exc:
                response = getattr(exc, "response", {})
                code = str(
                    response.get("ResponseMetadata", {}).get("HTTPStatusCode", "")
                )
                if code == "409" and attempt == 0:
                    # AWS documents retrying a conditional conflict. Retrying
                    # the same content-addressed conditional write is safe.
                    continue
                if code == "409":
                    raise OSError(
                        "Private S3 conditional write retry was exhausted"
                    ) from exc
                if code != "412":
                    raise
                # An identical content key is immutable and safe to reuse only
                # after the object metadata and byte count confirm its identity.
                head = self._client.head_object(Bucket=self.bucket, Key=key)
                metadata = head.get("Metadata", {})
                if metadata.get("sha256") != digest or head.get("ContentLength") != len(
                    content
                ):
                    raise OSError("Private S3 object identity mismatch") from exc
                break
        return key, digest

    def read(self, key: str, *, max_bytes: int | None = None) -> bytes:
        if not self._KEY.fullmatch(key):
            raise ValueError("Invalid private file key")
        limit = (
            self.max_object_bytes
            if max_bytes is None
            else min(self.max_object_bytes, max_bytes)
        )
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        size = int(response.get("ContentLength", 0))
        if size < 0 or size > limit:
            response["Body"].close()
            raise ValueError("Private file exceeds the configured read limit")
        content = cast(bytes, response["Body"].read(limit + 1))
        response["Body"].close()
        if len(content) != size or len(content) > limit:
            raise OSError("Private S3 object size mismatch")
        expected = key.removesuffix(".blob")
        digest = hashlib.sha256(content).hexdigest()
        if digest != expected or response.get("Metadata", {}).get("sha256") != expected:
            raise OSError("Private S3 object content hash mismatch")
        return content
