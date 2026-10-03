"""Outlook (Microsoft Graph) and IMAP mailbox sync.

Discovery lists unread Inbox messages and queues one idempotent job per
message; each job runs the intake pipeline, then marks the message read.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.services.document_intake.pipeline import process_document_intake_email
from app.services.document_intake.provider_adapters import OutlookGraphAdapter, IMAPDocumentAdapter


def _load_integration(integration_id: int) -> EmailIntegration | None:
    db = SessionLocal()
    try:
        integration = db.query(EmailIntegration).filter(
            EmailIntegration.id == integration_id,
            EmailIntegration.is_active == True,
        ).first()
        if integration:
            db.expunge(integration)
        return integration
    finally:
        db.close()


def _set_health(integration_id: int, status: str, message: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if row:
            previous = row.health_status
            row.health_status = status
            row.health_message = message[:1000]
            if status == "healthy":
                row.last_sync_at = datetime.now(timezone.utc)
            db.commit()
            from app.services.ops_alert import mailbox_health_changed
            mailbox_health_changed(row.email_address, previous, status, message)
    finally:
        db.close()


def renew_outlook_subscription(integration_id: int) -> None:
    """Renew (or recreate) the Graph change-notification subscription when it is close to expiry."""
    integration = _load_integration(integration_id)
    if not integration or integration.provider != "outlook":
        return
    if not integration.outlook_subscription_id or not settings.OUTLOOK_WEBHOOK_URL:
        return
    expires = integration.outlook_subscription_expires_at
    if expires and expires - datetime.now(timezone.utc) > timedelta(hours=12):
        return
    adapter = OutlookGraphAdapter(integration)
    try:
        adapter.renew_subscription(integration.outlook_subscription_id)
        logger.info(f"[provider_sync] Renewed Outlook subscription for integration {integration_id}")
    except Exception as exc:
        logger.warning(f"[provider_sync] Subscription renewal failed ({exc}); creating a new one")
        adapter.create_subscription(settings.OUTLOOK_WEBHOOK_URL)


# ── Discovery ─────────────────────────────────────────────────
async def sync_provider_mailbox(integration_id: int) -> int:
    """Queue a processing job for every unread message in an Outlook/IMAP mailbox."""
    from app.jobs.queue import enqueue

    integration = _load_integration(integration_id)
    if not integration or integration.provider not in ("outlook", "imap"):
        return 0

    try:
        if integration.provider == "outlook":
            adapter = OutlookGraphAdapter(integration)
            messages = await asyncio.to_thread(adapter.fetch_unseen)
            ids = [m["id"] for m in messages]
            job_name = "process_outlook_message"
        else:
            adapter = IMAPDocumentAdapter(integration)
            ids = await asyncio.to_thread(adapter.unseen_uids)
            job_name = "process_imap_message"
    except Exception as exc:
        logger.error(f"[provider_sync] {integration.provider} integration {integration_id} discovery failed: {exc}")
        _set_health(integration_id, "error", f"Sync failed: {exc}")
        raise

    for message_id in ids:
        await enqueue(job_name, integration_id, message_id,
                      job_id=f"{integration.provider}:{integration_id}:{message_id}")
    _set_health(integration_id, "healthy", f"Queued {len(ids)} message(s)")
    return len(ids)


# ── Per-message processing (runs as a job) ────────────────────
async def process_outlook_message(integration_id: int, graph_message_id: str) -> str:
    import httpx

    integration = _load_integration(integration_id)
    if not integration or integration.provider != "outlook":
        return "skipped"
    adapter = OutlookGraphAdapter(integration)
    try:
        message = await asyncio.to_thread(adapter.get_message, graph_message_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return "gone"
        raise

    status = await process_document_intake_email(integration_id, adapter, adapter.build_context(message))
    if status != "SKIPPED_OLD":
        await asyncio.to_thread(adapter.mark_read, graph_message_id)
    return status


async def process_imap_message(integration_id: int, uid: str) -> str:
    integration = _load_integration(integration_id)
    if not integration or integration.provider != "imap":
        return "skipped"
    adapter = IMAPDocumentAdapter(integration)
    item = await asyncio.to_thread(adapter.fetch_item, uid)
    if not item:
        return "gone"

    status = await process_document_intake_email(integration_id, adapter, adapter.context_for(item))
    if status != "SKIPPED_OLD":
        await asyncio.to_thread(adapter.mark_seen, uid)
    return status


# ── Backward-compatible entry points ──────────────────────────
async def sync_document_provider(integration_id: int) -> int:
    return await sync_provider_mailbox(integration_id)


async def sync_all_document_providers() -> int:
    db = SessionLocal()
    try:
        integration_ids = [
            row.id for row in db.query(EmailIntegration.id).filter(
                EmailIntegration.is_active == True,
                EmailIntegration.provider.in_(("outlook", "imap")),
            )
        ]
    finally:
        db.close()

    total = 0
    for integration_id in integration_ids:
        try:
            total += await sync_provider_mailbox(integration_id)
        except Exception:
            pass  # already logged + health set
    return total
