"""Nightly incremental FAQ re-index (spec Section 4.4).

A plain function with no Celery import, so the scheduler stays an
implementation detail and this can be run from a shell, a test, or any other
runner without change.
"""

import logging

from app.db.session import SessionLocal
from app.services.rag.indexer import reindex

logger = logging.getLogger(__name__)


def run() -> dict:
    with SessionLocal() as db:
        report = reindex(db)
    return report.as_dict()
