"""Private local/GCS storage contract with synthetic objects only."""

import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from google.api_core.exceptions import PreconditionFailed

from app.storage.file_store import PrivateFileStore
from app.storage.gcs_file_store import GCSFileStore


class MemoryBlob:
    def __init__(self, client: "MemoryGCS", key: str) -> None:
        self.client = client
        self.key = key
        self.metadata: dict[str, str] = {}
        self.size: Any = None
        self.generation: int | None = None

    def upload_from_string(self, content: bytes, **kwargs: Any) -> None:
        assert kwargs["if_generation_match"] == 0
        assert kwargs["checksum"] == "crc32c"
        assert kwargs["content_type"] == "application/octet-stream"
        if self.key in self.client.objects:
            raise PreconditionFailed("exists")  # type: ignore[no-untyped-call]
        self.client.objects[self.key] = (content, len(content), dict(self.metadata))

    def reload(self, **_kwargs: Any) -> None:
        content, self.size, self.metadata = self.client.objects[self.key]
        self.generation = 7

    def open(self, _mode: str, **_kwargs: Any) -> BytesIO:
        assert self.generation == 7
        self.client.stream = BytesIO(self.client.objects[self.key][0])
        return self.client.stream


class MemoryGCS:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, Any, dict[str, str]]] = {}
        self.stream: BytesIO | None = None

    def bucket(self, _name: str) -> "MemoryGCS":
        return self

    def blob(self, key: str) -> MemoryBlob:
        return MemoryBlob(self, key)


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


def test_gcs_create_only_duplicate_integrity_and_stream_cleanup() -> None:
    client = MemoryGCS()
    store = GCSFileStore("private-fixture", client=client, max_object_bytes=4)
    key, digest = store.put(b"safe")
    assert key == digest + ".blob"
    assert store.put(b"safe") == (key, digest)
    assert store.read(key) == b"safe"
    assert client.stream is not None and client.stream.closed
    client.objects[key] = (b"evil", 4, {"sha256": digest})
    with pytest.raises(OSError, match="hash mismatch"):
        store.put(b"safe")
    assert client.stream.closed


@pytest.mark.parametrize("size", [5, -1, "invalid", None])
def test_gcs_rejects_invalid_or_oversized_metadata(size: Any) -> None:
    client = MemoryGCS()
    store = GCSFileStore("private-fixture", client=client, max_object_bytes=4)
    key, digest = store.put(b"safe")
    client.objects[key] = (b"safe", size, {"sha256": digest})
    with pytest.raises((ValueError, OSError)):
        store.read(key)
    assert client.stream is None


def test_gcs_rejects_size_hash_key_and_read_write_bounds() -> None:
    client = MemoryGCS()
    store = GCSFileStore("private-fixture", client=client, max_object_bytes=4)
    with pytest.raises(ValueError, match="write limit"):
        store.put(b"large")
    with pytest.raises(ValueError, match="Invalid"):
        store.read("../outside")
    key, digest = store.put(b"safe")
    with pytest.raises(ValueError, match="read limit"):
        store.read(key, max_bytes=3)
    with pytest.raises(ValueError, match="negative"):
        store.read(key, max_bytes=-1)
    client.objects[key] = (b"shorter", 4, {"sha256": digest})
    with pytest.raises(OSError, match="size mismatch"):
        store.read(key)
    assert client.stream is not None and client.stream.closed
    client.objects[key] = (b"safe", 4, {"sha256": "0" * 64})
    with pytest.raises(OSError, match="hash mismatch"):
        store.read(key)


def test_gcs_stream_closes_on_download_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenStream(BytesIO):
        def read(self, _size: int | None = -1) -> bytes:
            raise OSError("synthetic download failure")

    stream = BrokenStream()
    monkeypatch.setattr(MemoryBlob, "open", lambda *_args, **_kwargs: stream)
    client = MemoryGCS()
    store = GCSFileStore("private-fixture", client=client)
    key, _ = store.put(b"safe")
    with pytest.raises(OSError, match="read unavailable"):
        store.read(key)
    assert stream.closed
