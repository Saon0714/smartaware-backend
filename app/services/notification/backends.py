"""Email delivery backends.

The console backend prints instead of sending, so the whole notification path
is exercisable locally without AWS credentials — including in tests, where it
records what would have been sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SentMessage:
    to: str
    subject: str
    body: str


@dataclass
class ConsoleBackend:
    """Prints messages and keeps them, so tests can assert on what was sent."""

    sent: list[SentMessage] = field(default_factory=list)

    def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append(SentMessage(to=to, subject=subject, body=body))
        print(
            f"\n{'=' * 70}\nEMAIL (console backend — not actually sent)\n"
            f"To:      {to}\nSubject: {subject}\n{'-' * 70}\n{body}\n{'=' * 70}\n"
        )

    def clear(self) -> None:
        self.sent.clear()


class SesBackend:
    """AWS SES delivery."""

    def send(self, *, to: str, subject: str, body: str) -> None:
        import boto3

        client = boto3.client("ses", region_name=settings.AWS_REGION)
        client.send_email(
            Source=settings.SES_SENDER_EMAIL,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )


#: A module-level console backend so tests can inspect it without wiring.
console_backend = ConsoleBackend()


def get_backend():
    return console_backend if settings.USE_CONSOLE_EMAIL else SesBackend()
