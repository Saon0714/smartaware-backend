from app.core.config import settings
from app.services.storage.base import (
    Storage,
    StorageError,
    StoredObject,
    build_key,
    safe_filename,
)

_backend: Storage | None = None


def get_storage() -> Storage:
    global _backend
    if _backend is None:
        if settings.USE_LOCAL_STORAGE:
            from app.services.storage.local import LocalStorage

            _backend = LocalStorage()
        else:
            from app.services.storage.s3 import S3Storage

            _backend = S3Storage()
    return _backend


def set_storage(backend: Storage | None) -> None:
    """Override the backend, for tests."""
    global _backend
    _backend = backend


__all__ = [
    "Storage",
    "StorageError",
    "StoredObject",
    "build_key",
    "get_storage",
    "safe_filename",
    "set_storage",
]
