"""Select one private file backend for every storage consumer."""

from app.config import Settings
from app.storage.file_store import FileStore, PrivateFileStore


def create_file_store(settings: Settings) -> FileStore:
    if settings.file_storage_backend == "local":
        return PrivateFileStore(
            settings.private_file_dir, max_object_bytes=settings.max_private_file_bytes
        )
    if settings.file_storage_backend == "gcs":
        from app.storage.gcs_file_store import GCSFileStore

        if settings.private_gcs_bucket is None:
            raise ValueError("GCS storage requires PRIVATE_GCS_BUCKET")
        return GCSFileStore(
            settings.private_gcs_bucket,
            project=settings.gcp_project,
            max_object_bytes=settings.max_private_file_bytes,
        )
    raise ValueError(
        f"Unsupported file storage backend: {settings.file_storage_backend}"
    )
