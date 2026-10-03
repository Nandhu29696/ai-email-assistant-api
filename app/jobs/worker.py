"""ARQ worker settings: ``arq app.jobs.worker.WorkerSettings``."""
from __future__ import annotations

from arq import cron
from arq.worker import func

from app.config import settings
from app.jobs import tasks
from app.jobs.queue import REGISTRY, redis_settings
from app.observability import configure_logging


async def startup(ctx) -> None:
    configure_logging()
    from app.worker import seed_templates
    seed_templates()


class WorkerSettings:
    functions = [
        func(runner, name=name, max_tries=getattr(runner, "max_tries", settings.JOB_MAX_TRIES),
             timeout=settings.JOB_TIMEOUT_SECONDS, keep_result=60)
        for name, runner in REGISTRY.items()
    ]
    cron_jobs = [
        cron(tasks.cron_schedule_syncs, second={0, 30}, run_at_startup=True, unique=True),
        cron(tasks.cron_renew_push, minute=7, second=0, run_at_startup=True, unique=True),
        cron(tasks.cron_retention, hour=2, minute=17, second=0, unique=True),
    ]
    on_startup = startup
    redis_settings = redis_settings()
    max_jobs = 10
    job_timeout = settings.JOB_TIMEOUT_SECONDS
    keep_result = 60
    health_check_interval = 30
