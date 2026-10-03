"""Background job definitions (ARQ functions + cron) and maintenance helpers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.jobs.queue import enqueue, job
from app.models.email import EmailIntegration


# ── Mailbox sync ──────────────────────────────────────────────
@job("sync_mailbox", max_tries=3)
async def sync_mailbox(integration_id: int) -> int:
    db = SessionLocal()
    try:
        provider = db.query(EmailIntegration.provider).filter(
            EmailIntegration.id == integration_id, EmailIntegration.is_active == True,
        ).scalar()
    finally:
        db.close()
    if provider == "gmail":
        from app.services.gmail_sync import sync_gmail_integration
        return await sync_gmail_integration(integration_id)
    if provider in ("outlook", "imap"):
        from app.services.document_intake.provider_sync import sync_provider_mailbox
        return await sync_provider_mailbox(integration_id)
    return 0


@job("process_gmail_message")
async def process_gmail_message(integration_id: int, gmail_message_id: str) -> str:
    from app.services.gmail_sync import process_gmail_message as run
    return await run(integration_id, gmail_message_id)


@job("process_outlook_message")
async def process_outlook_message(integration_id: int, graph_message_id: str) -> str:
    from app.services.document_intake.provider_sync import process_outlook_message as run
    return await run(integration_id, graph_message_id)


@job("process_imap_message")
async def process_imap_message(integration_id: int, uid: str) -> str:
    from app.services.document_intake.provider_sync import process_imap_message as run
    return await run(integration_id, uid)


# ── Manual reprocessing ───────────────────────────────────────
@job("reprocess_batch", max_tries=2)
async def reprocess_batch(batch_id: int) -> str:
    from app.services.document_intake.pipeline import reprocess_batch as run
    return await run(batch_id)


# ── Periodic work ─────────────────────────────────────────────
async def schedule_mailbox_syncs(force: bool = False) -> int:
    """Queue a sync for each active mailbox whose interval has elapsed (idempotent per mailbox)."""
    now = datetime.now(timezone.utc)
    interval = timedelta(seconds=max(30, settings.FETCH_INTERVAL_SECONDS))
    db = SessionLocal()
    try:
        rows = db.query(EmailIntegration.id, EmailIntegration.last_sync_at).filter(
            EmailIntegration.is_active == True,
            EmailIntegration.access_token.isnot(None) | (EmailIntegration.provider == "imap"),
        ).all()
    finally:
        db.close()
    queued = 0
    for integration_id, last_sync_at in rows:
        if force or last_sync_at is None or now - last_sync_at >= interval - timedelta(seconds=5):
            if await enqueue("sync_mailbox", integration_id, job_id=f"sync:{integration_id}") != "duplicate":
                queued += 1
    return queued


def _renew_push_subscriptions() -> None:
    from app.services.gmail_sync import ensure_gmail_watch
    from app.services.document_intake.provider_sync import renew_outlook_subscription

    db = SessionLocal()
    try:
        rows = db.query(EmailIntegration.id, EmailIntegration.provider).filter(
            EmailIntegration.is_active == True,
        ).all()
    finally:
        db.close()
    for integration_id, provider in rows:
        try:
            if provider == "gmail":
                ensure_gmail_watch(integration_id)
            elif provider == "outlook":
                renew_outlook_subscription(integration_id)
        except Exception as exc:
            logger.warning(f"[jobs] Push subscription renewal failed for integration {integration_id}: {exc}")


_last_maintenance: dict[str, datetime] = {}


async def run_periodic_maintenance() -> None:
    """Push-subscription renewal (hourly) and retention clean-up (daily)."""
    from app.services.document_intake.retention_service import archive_old_batches

    now = datetime.now(timezone.utc)
    schedule = {
        "push": (timedelta(hours=1), _renew_push_subscriptions),
        "retention": (timedelta(seconds=settings.RETENTION_CHECK_INTERVAL_SECONDS), archive_old_batches),
    }
    for key, (every, fn) in schedule.items():
        last = _last_maintenance.get(key)
        if last is None or now - last >= every:
            _last_maintenance[key] = now
            try:
                await asyncio.to_thread(fn)
            except Exception as exc:
                logger.error(f"[jobs] Maintenance task '{key}' failed: {exc}")


# ARQ cron entry points (ctx is the ARQ worker context)
async def cron_schedule_syncs(ctx) -> None:
    await schedule_mailbox_syncs()


async def cron_renew_push(ctx) -> None:
    await asyncio.to_thread(_renew_push_subscriptions)


async def cron_retention(ctx) -> None:
    from app.services.document_intake.retention_service import archive_old_batches
    await asyncio.to_thread(archive_old_batches)
