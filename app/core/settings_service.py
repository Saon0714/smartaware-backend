"""Runtime settings backed by the `settings` table.

Anything SmartAWARE staff must be able to change without a deploy is read
through here. Spec Section 13 lists thirteen questions still open; each one
that needed a default became a row rather than a literal, so revisiting a
decision is an admin edit and not a code change.

Reads are cached per-process with a short TTL — these are hit on nearly every
request, and a stale value for a few seconds is harmless for the kinds of
values stored here.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.setting import Setting

_CACHE_TTL_SECONDS = 30
_cache: dict[str, tuple[float, Any]] = {}
_lock = threading.Lock()


class SettingKey:
    """Canonical keys. Referencing a constant rather than a bare string means a
    typo is an import error instead of a silent None."""

    # Section 13 item 7 — escalation threshold
    CHAT_SIMILARITY_THRESHOLD = "chat_similarity_threshold"
    CHAT_TOP_K = "chat_top_k"
    # Section 4.5 — conversation retention
    # Section 13 item 8 — who may read chat transcripts
    # Section 5.1 — invite expiry
    INVITE_EXPIRY_DAYS = "invite_expiry_days"
    # Section 13 item 4 — single vs. multiple admins
    ALLOW_MULTIPLE_ADMINS = "allow_multiple_admins"
    # Section 13 item 5 — manager visibility scope
    MANAGER_CLIENT_SCOPE = "manager_client_scope"
    # Section 13 item 6 — manager access to content management
    MANAGER_CAN_MANAGE_CONTENT = "manager_can_manage_content"
    # Section 13 item 11 — MFA
    MFA_REQUIRED_ROLES = "mfa_required_roles"
    # Section 13 item 12 — document versioning
    DOCUMENT_VERSIONING = "document_versioning"
    # Section 7 — notification recipients
    NOTIFY_ENQUIRY_RECIPIENTS = "notify_enquiry_recipients"
    NOTIFY_DOCUMENT_RECIPIENTS = "notify_document_recipients"
    # Section 3.1 — soft editorial guidance, not a constraint
    SERVICE_SHORT_DESCRIPTION_MIN_WORDS = "service_short_description_min_words"
    SERVICE_SHORT_DESCRIPTION_MAX_WORDS = "service_short_description_max_words"
    # Section 12 — Wise Open Payment Link
    WISE_PAYMENT_LINK_BASE_URL = "wise_payment_link_base_url"


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    value = row.value if row is not None else default

    with _lock:
        _cache[key] = (now + _CACHE_TTL_SECONDS, value)
    return value


def set_setting(db: Session, key: str, value: Any, updated_by_id: Any = None) -> Setting:
    row = db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row is None:
        raise KeyError(f"Unknown setting: {key}")
    row.value = value
    row.updated_by_id = updated_by_id
    db.flush()
    invalidate(key)
    return row


def invalidate(key: str | None = None) -> None:
    with _lock:
        if key is None:
            _cache.clear()
        else:
            _cache.pop(key, None)
