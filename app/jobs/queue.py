"""
Background job queue.

Jobs run on ARQ (Redis) when it is reachable, with retries + exponential
backoff, idempotent job ids and a dead-letter table (``failed_jobs``) for jobs
that exhaust their retries. When Redis is unavailable (local development,
Redis outage) the same job functions run in-process with the same retry and
dead-letter semantics, so nothing is silently dropped.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from loguru import logger

from app.config import settings

JobFunc = Callable[..., Awaitable[Any]]

# name -> wrapped coroutine taking (ctx, *args)
REGISTRY: dict[str, JobFunc] = {}

_pools: dict[int, Any] = {}
_pool_failed_until = 0.0
_inline_running: set[str] = set()
_inline_tasks: set[asyncio.Task] = set()
_inline_semaphores: dict[int, asyncio.Semaphore] = {}
# True when this process both schedules and runs the jobs (the API with
# RUN_BACKGROUND_WORKERS). Jobs must then run here, not wait in Redis for a
# separate worker that may not exist.
_inline_only = False


def use_inline_only(enabled: bool = True) -> None:
    global _inline_only
    _inline_only = enabled


def backoff_seconds(attempt: int) -> int:
    """5s, 20s, 80s, 320s … capped at 30 minutes."""
    return min(1800, 5 * 4 ** max(0, attempt - 1))


def record_dead_letter(name: str, args: tuple, job_key: str | None, attempts: int, error: BaseException) -> None:
    from app.database import SessionLocal
    from app.models.user import FailedJob

    db = SessionLocal()
    try:
        db.add(FailedJob(
            job_name=name,
            args_json=list(args),
            job_key=job_key,
            attempts=attempts,
            error=f"{type(error).__name__}: {error}"[:5000],
            status="failed",
        ))
        db.commit()
    except Exception as exc:  # the DLQ must never crash the worker
        logger.error(f"[jobs] Could not record dead letter for {name}{args}: {exc}")
        db.rollback()
    finally:
        db.close()
    from app.observability import JOBS_TOTAL
    JOBS_TOTAL.labels(name, "dead_letter").inc()


def job(name: str | None = None, max_tries: int | None = None):
    """Register an async function ``fn(*args)`` as a background job."""

    def decorator(fn: JobFunc) -> JobFunc:
        job_name = name or fn.__name__
        tries = max_tries or settings.JOB_MAX_TRIES

        async def runner(ctx: dict, *args):
            from app.observability import JOBS_TOTAL, JOB_DURATION

            attempt = int(ctx.get("job_try") or 1)
            started = time.perf_counter()
            with logger.contextualize(job=job_name, job_id=ctx.get("job_id"), attempt=attempt):
                try:
                    result = await fn(*args)
                    JOBS_TOTAL.labels(job_name, "success").inc()
                    return result
                except Exception as exc:
                    if attempt < tries:
                        delay = backoff_seconds(attempt)
                        logger.warning(f"[jobs] {job_name}{args} failed (attempt {attempt}/{tries}), retrying in {delay}s: {exc}")
                        JOBS_TOTAL.labels(job_name, "retry").inc()
                        from arq import Retry
                        raise Retry(defer=delay) from exc
                    logger.error(f"[jobs] {job_name}{args} failed permanently after {attempt} attempts: {exc}")
                    record_dead_letter(job_name, args, ctx.get("job_id"), attempt, exc)
                    return None
                finally:
                    JOB_DURATION.labels(job_name).observe(time.perf_counter() - started)

        runner.__name__ = job_name
        runner.__qualname__ = job_name
        runner.max_tries = tries  # type: ignore[attr-defined]
        REGISTRY[job_name] = runner
        return fn

    return decorator


def _is_dead_lettered(job_key: str) -> bool:
    from app.database import SessionLocal
    from app.models.user import FailedJob

    db = SessionLocal()
    try:
        return db.query(FailedJob.id).filter(
            FailedJob.job_key == job_key, FailedJob.status == "failed",
        ).first() is not None
    except Exception:
        return False
    finally:
        db.close()


def redis_settings():
    from arq.connections import RedisSettings

    rs = RedisSettings.from_dsn(settings.REDIS_URL)
    rs.conn_timeout = 2
    rs.conn_retries = 0
    return rs


async def _get_pool():
    """Return an ARQ pool for this event loop, or None when Redis is unavailable."""
    global _pool_failed_until
    if _inline_only or not settings.JOB_QUEUE_ENABLED or not settings.REDIS_URL:
        return None
    loop_key = id(asyncio.get_running_loop())
    if loop_key in _pools:
        return _pools[loop_key]
    if time.monotonic() < _pool_failed_until:
        return None
    try:
        from arq import create_pool
        pool = await asyncio.wait_for(create_pool(redis_settings()), timeout=5)
        _pools[loop_key] = pool
        return pool
    except Exception as exc:
        _pool_failed_until = time.monotonic() + 60
        logger.warning(f"[jobs] Redis unavailable ({exc}); running jobs in-process for the next 60s")
        return None


async def enqueue(name: str, *args, job_id: str | None = None, defer_seconds: float | None = None) -> str:
    """Queue a job. ``job_id`` makes enqueueing idempotent while the job is pending/running.

    Returns ``"queued"``, ``"duplicate"``, ``"inline"`` or ``"dead_lettered"``.
    """
    if name not in REGISTRY:
        raise KeyError(f"Unknown job '{name}'")
    if job_id and await asyncio.to_thread(_is_dead_lettered, job_id):
        # Don't loop a permanently failing message through retries on every sync;
        # an admin can retry it from the dead-letter queue.
        return "dead_lettered"
    pool = await _get_pool()
    if pool is not None:
        try:
            queued = await pool.enqueue_job(name, *args, _job_id=job_id, _defer_by=defer_seconds)
            return "queued" if queued is not None else "duplicate"
        except Exception as exc:
            logger.warning(f"[jobs] Enqueue of {name} failed ({exc}); running in-process")
    return _run_inline(name, args, job_id, defer_seconds)


def _run_inline(name: str, args: tuple, job_id: str | None, defer_seconds: float | None) -> str:
    key = job_id or f"{name}:{args}"
    if key in _inline_running:
        return "duplicate"
    _inline_running.add(key)

    loop_key = id(asyncio.get_running_loop())
    semaphore = _inline_semaphores.setdefault(loop_key, asyncio.Semaphore(settings.JOB_INLINE_CONCURRENCY))

    async def _execute():
        from arq import Retry
        try:
            if defer_seconds:
                await asyncio.sleep(defer_seconds)
            runner = REGISTRY[name]
            max_tries = getattr(runner, "max_tries", settings.JOB_MAX_TRIES)
            for attempt in range(1, max_tries + 1):
                try:
                    async with semaphore:
                        return await runner({"job_try": attempt, "job_id": key}, *args)
                except Retry as retry:
                    delay = retry.defer_score / 1000 if retry.defer_score else backoff_seconds(attempt)
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"[jobs] Inline job {name} crashed: {exc}")
        finally:
            _inline_running.discard(key)

    task = asyncio.create_task(_execute())
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)
    return "inline"


def mark_resolved(failed_job_id: int, status: str) -> None:
    from app.database import SessionLocal
    from app.models.user import FailedJob

    db = SessionLocal()
    try:
        row = db.query(FailedJob).filter(FailedJob.id == failed_job_id).first()
        if row:
            row.status = status
            row.resolved_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
