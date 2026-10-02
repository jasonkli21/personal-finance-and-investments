"""Private owner-only storage for imported source bytes."""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path


class PrivateFileStore:
    """Write immutable content-addressed files with owner-only permissions."""

    _KEY = re.compile(r"^[0-9a-f]{64}\.blob$")

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().absolute()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError("PRIVATE_FILE_DIR must be a real directory")
        os.chmod(self.root, 0o700)

    def put(self, content: bytes) -> tuple[str, str]:
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

    def read(self, key: str) -> bytes:
        if not self._KEY.fullmatch(key):
            raise ValueError("Invalid private file key")
        path = self.root / key
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
