"""Background worker.

With Redis available this runs the ARQ worker (``app.jobs.worker.WorkerSettings``):
queued jobs with retries, a dead-letter table and cron scheduling. Without
Redis it falls back to an in-process scheduler running the same jobs.
"""
from __future__ import annotations

import asyncio

from loguru import logger

from app.config import settings
from app.observability import configure_logging


def seed_templates() -> None:
    from app.database import SessionLocal
    from app.services.document_intake.template_renderer import seed_default_templates

    db = SessionLocal()
    try:
        seed_default_templates(db)
    except Exception as exc:
        logger.warning(f"Template seeding skipped: {exc}")
        db.rollback()
    finally:
        db.close()


def _redis_available() -> bool:
    if not settings.JOB_QUEUE_ENABLED or not settings.REDIS_URL:
        return False
    try:
        import redis
        redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2).ping()
        return True
    except Exception as exc:
        logger.warning(f"Redis unavailable ({exc}); using the in-process scheduler")
        return False


async def run_inprocess_workers() -> None:
    import app.jobs  # noqa: F401  (register jobs)
    from app.services.gmail_sync import start_email_poller

    await asyncio.to_thread(seed_templates)
    await start_email_poller()


def main() -> None:
    configure_logging()
    if _redis_available():
        from arq import run_worker
        from app.jobs.worker import WorkerSettings

        logger.info("Starting ARQ background worker")
        run_worker(WorkerSettings)
        return

    logger.info("Starting in-process background worker")
    try:
        asyncio.run(run_inprocess_workers())
    except KeyboardInterrupt:
        logger.info("Background worker stopped")


if __name__ == "__main__":
    main()
