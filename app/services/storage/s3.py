"""AWS S3 storage."""

from __future__ import annotations

import logging
from urllib.parse import quote

from app.core.config import settings
from app.services.storage.base import StorageError, StoredObject

logger = logging.getLogger(__name__)


class S3Storage:
    def __init__(self) -> None:
        import boto3

        self._client = boto3.client("s3", region_name=settings.AWS_REGION)
        self._bucket = settings.S3_BUCKET

    def put(self, key: str, data: bytes, content_type: str | None) -> StoredObject:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type or "application/octet-stream",
                # Spec Section 9 asks for encrypted storage of uploaded
                # documents. Set per object so it holds even if the bucket
                # default is ever changed.
                ServerSideEncryption="AES256",
            )
        except Exception as exc:
            logger.exception("S3 upload failed for %s", key)
            raise StorageError("The file could not be stored.") from exc
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:
            logger.exception("S3 download failed for %s", key)
            raise StorageError("The file could not be retrieved.") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except Exception:
            logger.exception("S3 delete failed for %s", key)

    def download_url(self, key: str, *, filename: str, expires_in: int) -> str | None:
        """A short-lived signed URL.

        The link is what the browser follows, so it must expire quickly: a URL
        pasted into an email or left in browser history should not keep working
        as a permanent handle on a client's tax document.
        """
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    "ResponseContentDisposition": (f'attachment; filename="{quote(filename)}"'),
                },
                ExpiresIn=expires_in,
            )
        except Exception:
            logger.exception("Could not sign a URL for %s", key)
            return None
