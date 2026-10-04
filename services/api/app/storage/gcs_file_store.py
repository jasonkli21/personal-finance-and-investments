"""Private immutable GCS storage using application default credentials."""

import hashlib
import re
from typing import Any, cast

from google.api_core.exceptions import PreconditionFailed


class GCSFileStore:
    _KEY = re.compile(r"^[0-9a-f]{64}\.blob$")

    def __init__(
        self,
        bucket: str,
        *,
        project: str | None = None,
        max_object_bytes: int = 20_000_000,
        client: Any | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("Private GCS bucket is required")
        if max_object_bytes < 1:
            raise ValueError("Private file size limit must be positive")
        if client is None:
            from google.cloud import storage  # type: ignore[attr-defined]

            client = storage.Client(project=project)
        self._bucket = client.bucket(bucket)
        self.max_object_bytes = max_object_bytes

    def put(self, content: bytes) -> tuple[str, str]:
        if len(content) > self.max_object_bytes:
            raise ValueError("Private file exceeds the configured write limit")
        digest = hashlib.sha256(content).hexdigest()
        key = f"{digest}.blob"
        blob = self._bucket.blob(key)
        blob.metadata = {"sha256": digest}
        try:
            # Generation zero means create only; the SDK's conditional retry
            # policy can safely repeat this write without replacing an original.
            blob.upload_from_string(
                content,
                content_type="application/octet-stream",
                if_generation_match=0,
                checksum="crc32c",
                timeout=30,
            )
        except PreconditionFailed:
            # Metadata alone cannot establish identity of an existing object.
            if len(self.read(key)) != len(content):
                raise OSError("Private GCS object identity mismatch") from None
        except Exception as exc:
            raise OSError("Private GCS write unavailable") from exc
        return key, digest

    def read(self, key: str, *, max_bytes: int | None = None) -> bytes:
        if not self._KEY.fullmatch(key):
            raise ValueError("Invalid private file key")
        limit = (
            self.max_object_bytes
            if max_bytes is None
            else min(self.max_object_bytes, max_bytes)
        )
        if limit < 0:
            raise ValueError("Private file read limit cannot be negative")
        blob = self._bucket.blob(key)
        try:
            blob.reload(timeout=30)
            size = int(blob.size)
            if size < 0 or size > limit:
                raise ValueError("Private file exceeds the configured read limit")
            if blob.generation is None:
                raise OSError("Private GCS object generation unavailable")
            # reload pins generation, preventing a metadata/read replacement
            # race. Context management closes the ranged stream even on error.
            with blob.open("rb", chunk_size=256 * 1024, timeout=30) as stream:
                content = cast(bytes, stream.read(limit + 1))
        except ValueError:
            raise
        except Exception as exc:
            raise OSError("Private GCS read unavailable") from exc
        if len(content) != size or len(content) > limit:
            raise OSError("Private GCS object size mismatch")
        expected = key.removesuffix(".blob")
        if (
            hashlib.sha256(content).hexdigest() != expected
            or (blob.metadata or {}).get("sha256") != expected
        ):
            raise OSError("Private GCS object content hash mismatch")
        return content
