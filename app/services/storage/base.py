"""Object storage interface.

Two implementations: S3 for real deployments, and a local filesystem backend so
the whole document flow — upload, listing, download, versioning — works without
AWS credentials.

Keys are random rather than derived from the filename or the client. A key is
never the authorisation: every download is scope-checked server-side first.
But predictable keys turn any future misconfiguration of the bucket into a
browsable archive of other clients' tax documents, so they are unguessable too.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Protocol


class StorageError(Exception):
    """The object could not be stored or retrieved."""


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str | None


def safe_filename(name: str) -> str:
    """Reduce an uploaded filename to something safe to store and echo back.

    The stored key never uses this — it exists so the name shown to a user, and
    written into a Content-Disposition header, cannot carry path separators,
    control characters or a misleading right-to-left override.
    """
    name = unicodedata.normalize("NFKC", name)
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ord(ch) > 31)
    name = re.sub(r'[<>:"|?*\x7f]', "", name).strip(" .")
    name = re.sub(r"\s+", " ", name)
    if not name:
        return "document"
    return name[:255]


def build_key(client_id, direction: str, filename: str) -> str:
    """A random, unguessable object key.

    The client id and date are only a browsing convenience for whoever has
    legitimate access to the bucket; the random component is what makes the key
    impossible to guess or enumerate.
    """
    suffix = ""
    cleaned = safe_filename(filename)
    if "." in cleaned:
        suffix = "." + cleaned.rsplit(".", 1)[1].lower()[:10]
    today = date.today()
    return f"clients/{client_id}/{direction}/{today:%Y/%m}/{secrets.token_urlsafe(24)}{suffix}"


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str | None) -> StoredObject: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def download_url(self, key: str, *, filename: str, expires_in: int) -> str | None:
        """A time-limited direct link, or None if this backend cannot issue one
        and the caller should stream the bytes instead."""
        ...
