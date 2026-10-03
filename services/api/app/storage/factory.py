"""Select one explicit private file backend for every storage consumer."""

from app.config import Settings
from app.storage.file_store import FileStore, PrivateFileStore


def create_file_store(settings: Settings) -> FileStore:
    if settings.file_storage_backend == "local":
        return PrivateFileStore(
            settings.private_file_dir,
            max_object_bytes=settings.max_private_file_bytes,
        )
    if settings.file_storage_backend == "s3":
        from app.storage.s3_file_store import S3FileStore

        if settings.aws_region is None or settings.private_s3_bucket is None:
            raise ValueError("S3 storage requires AWS_REGION and PRIVATE_S3_BUCKET")
        return S3FileStore(
            settings.private_s3_bucket,
            settings.aws_region,
            kms_key_id=settings.private_s3_kms_key_id,
            max_object_bytes=settings.max_private_file_bytes,
        )
    raise ValueError(
        f"Unsupported file storage backend: {settings.file_storage_backend}"
    )
