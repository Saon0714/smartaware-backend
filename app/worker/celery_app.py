"""Celery application and schedule.

Celery over APScheduler because the scheduler must survive the web process and
must not double-fire when more than one instance is running, and because email
dispatch wants a retry queue rather than a best-effort call inside a request.

The trade is more infrastructure: a broker plus worker and beat processes. To
keep that reversible, every job is a plain function in `app.jobs` and the tasks
below are thin wrappers — swapping schedulers means rewriting this file only.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "smartaware",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # A stuck embedding call must not hold a worker slot indefinitely.
    task_time_limit=15 * 60,
    task_soft_time_limit=14 * 60,
    worker_max_tasks_per_child=200,
)


@celery_app.task(name="faq.reindex", bind=True, max_retries=2)
def reindex_faq_task(self):
    from app.jobs.reindex_faq import run

    try:
        return run()
    except Exception as exc:
        # Entries stay stale, so a retry picks up exactly the same delta.
        raise self.retry(exc=exc, countdown=300) from exc


celery_app.conf.beat_schedule = {
    # Nightly and incremental. It runs every night even when nothing changed —
    # Section 4.4 requires a no-op run rather than a skipped one, so a late
    # edit cannot sit unindexed.
    "reindex-faq-nightly": {
        "task": "faq.reindex",
        "schedule": crontab(hour=2, minute=30),
    },
}
