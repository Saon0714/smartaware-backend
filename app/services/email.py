"""Minimal email dispatch.

A deliberate placeholder. Spec Section 7 requires a single shared notification
service with centrally-managed recipients and templates; that lands in Chunk 5
and will replace this module's internals. The interface is kept narrow so that
swap touches nothing else.

Locally (`USE_CONSOLE_EMAIL=true`) messages are printed instead of sent, so the
invite flow is exercisable end to end without AWS credentials.
"""

from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(*, to: str, subject: str, body: str) -> None:
    if settings.USE_CONSOLE_EMAIL:
        print(
            f"\n{'=' * 70}\nEMAIL (console backend — not actually sent)\n"
            f"To:      {to}\nSubject: {subject}\n{'-' * 70}\n{body}\n{'=' * 70}\n"
        )
        return

    # Chunk 5 replaces this with the shared notification service over SES.
    raise NotImplementedError(
        "SES delivery arrives with the notification service in Chunk 5. "
        "Set USE_CONSOLE_EMAIL=true for local development."
    )
