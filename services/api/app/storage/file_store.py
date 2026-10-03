"""Private owner-only storage for imported source bytes."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path
from typing import Protocol


class FileStore(Protocol):
    """Private immutable file operations shared by local and cloud storage."""

    def put(self, content: bytes) -> tuple[str, str]: ...

    def read(self, key: str, *, max_bytes: int | None = None) -> bytes: ...


class PrivateFileStore:
    """Write immutable content-addressed files with owner-only permissions."""

    _KEY = re.compile(r"^[0-9a-f]{64}\.blob$")

    def __init__(self, root: str | Path, *, max_object_bytes: int = 20_000_000) -> None:
        if max_object_bytes < 1:
            raise ValueError("Private file size limit must be positive")
        self.root = Path(root).expanduser().absolute()
        self.max_object_bytes = max_object_bytes
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("PRIVATE_FILE_DIR must be a real directory")
        os.chmod(self.root, 0o700)

    def put(self, content: bytes) -> tuple[str, str]:
        if len(content) > self.max_object_bytes:
            raise ValueError("Private file exceeds the configured write limit")
        digest = hashlib.sha256(content).hexdigest()
        key = f"{digest}.blob"
        destination = self.root / key
        if destination.exists():
            if destination.is_symlink():
                raise OSError("Private file path cannot be a symbolic link")
            if self._hash_file(destination) != digest:
                raise OSError("Private file content hash mismatch")
            return key, digest

        temporary = self.root / f".stage-{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
        else:
            os.close(descriptor)

        try:
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        return key, digest

    def read(self, key: str, *, max_bytes: int | None = None) -> bytes:
        if not self._KEY.fullmatch(key):
            raise ValueError("Invalid private file key")
        path = self.root / key
        limit = (
            self.max_object_bytes
            if max_bytes is None
            else min(self.max_object_bytes, max_bytes)
        )
        if limit < 0:
            raise ValueError("Private file read limit cannot be negative")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise FileNotFoundError(key)
            if metadata.st_size > limit:
                raise ValueError("Private file exceeds the configured read limit")
            content = stream.read(limit + 1)
        if len(content) > limit:
            raise ValueError("Private file exceeds the configured read limit")
        if hashlib.sha256(content).hexdigest() != key.removesuffix(".blob"):
            raise OSError("Private file content hash mismatch")
        return content

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise OSError("Private file path must be a regular file")
            if metadata.st_size > self.max_object_bytes:
                raise ValueError("Private file exceeds the configured write limit")
            for block in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
