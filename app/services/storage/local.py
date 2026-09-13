"""Filesystem storage for local development and tests."""

from __future__ import annotations

from pathlib import Path

from app.services.storage.base import StorageError, StoredObject


class LocalStorage:
    def __init__(self, root: str | Path = "uploads") -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        root = self.root.resolve()
        # A key is generated server-side, but resolving and checking costs
        # nothing and stops a malformed one escaping the upload directory.
        if not str(path).startswith(str(root)):
            raise StorageError("Refusing to write outside the storage root.")
        return path

    def put(self, key: str, data: bytes, content_type: str | None) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise StorageError("Stored file is missing.")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def download_url(self, key: str, *, filename: str, expires_in: int) -> str | None:
        # No signed URLs locally; the API streams the bytes instead.
        return None
