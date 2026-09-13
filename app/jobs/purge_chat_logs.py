"""Scheduled chat transcript cleanup (spec Section 4.5)."""

import logging

from app.db.session import SessionLocal
from app.services.rag.chat import purge_expired_logs

logger = logging.getLogger(__name__)


def run() -> dict:
    with SessionLocal() as db:
        purged = purge_expired_logs(db)
    return {"purged_sessions": purged}
