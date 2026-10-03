"""
Gmail sync service.

Sync is incremental: after an initial baseline (unread Inbox messages), new
mail is discovered with ``users.history.list`` from the stored ``historyId``,
so messages are found regardless of their read state. When
``GMAIL_PUBSUB_TOPIC`` is configured, ``users.watch`` push notifications
trigger syncs in near real time (polling remains as a safety net).

Each discovered message is processed by its own idempotent, retryable
background job (``process_gmail_message``) that runs the intake pipeline.

All Gmail API calls are blocking (googleapiclient) and run in worker threads.
"""
from __future__ import annotations

import asyncio
import base64
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timedelta, timezone
from typing import Any, cast

from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.services.gmail_client import build_gmail_service, GmailAuthError

_SKIP_LABELS = {"DRAFT", "SENT", "SPAM", "TRASH"}


def _mark_message_read(service, msg_id: str) -> None:
    """Best-effort: remove UNREAD so processed messages are visibly handled."""
    try:
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except Exception as exc:
        logger.warning(f"[gmail_sync] Failed to mark message {msg_id} as read: {exc}")


# Re-exported for older imports.
from app.services.document_intake.sender_checks import sender_authentication_failed  # noqa: E402,F401


# ── Body extraction ───────────────────────────────────────────

def _extract_gmail_body(payload: dict) -> tuple[str, str]:
    """Recursively extract plain-text and HTML body from a Gmail API payload."""
    plain, html = "", ""
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain" and not payload.get("filename"):
        data = payload.get("body", {}).get("data", "")
        if data:
            plain = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    elif mime_type == "text/html" and not payload.get("filename"):
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
    elif "parts" in payload:
        for part in payload["parts"]:
            p, h = _extract_gmail_body(part)
            plain = plain or p
            html = html or h

    return plain, html


def _parse_received_at(date_str: str) -> datetime:
    try:
        value = parsedate_to_datetime(date_str)
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def build_intake_context_from_gmail(msg: dict, recipient_addr: str):
    """Build the document-intake context for a Gmail API ``format=full`` message."""
    from app.services.document_intake.pipeline import IntakeEmailContext
    from app.services.preprocessor import strip_html

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    lower_headers = {k.lower(): v for k, v in headers.items()}
    gmail_msg_id = msg["id"]
    message_id_header = lower_headers.get("message-id", "").strip().strip("<>")
    sender_name, sender_email = parseaddr(lower_headers.get("from", ""))

    plain, html = _extract_gmail_body(msg.get("payload", {}))
    if not plain and html:
        plain = strip_html(html)
    intake_headers = dict(headers)
    intake_headers["_body_plain"] = plain

    return IntakeEmailContext(
        gmail_message_id=gmail_msg_id,
        stored_message_id=message_id_header or gmail_msg_id,
        thread_id=msg.get("threadId"),
        headers=intake_headers,
        sender_name=sender_name,
        sender_email=sender_email,
        recipient_email=recipient_addr,
        subject=lower_headers.get("subject") or "(no subject)",
        received_at=_parse_received_at(lower_headers.get("date", "")),
        payload=msg.get("payload", {}),
    )


def _update_health(integration_id: int, status: str, message: str, new_count: int = 0, **fields) -> None:
    db = SessionLocal()
    try:
        row = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if row:
            status_row = cast(Any, row)
            now = datetime.now(timezone.utc)
            if status == "healthy":
                status_row.last_sync_at = now
                if new_count:
                    status_row.last_email_processed_at = now
            previous = status_row.health_status
            status_row.health_status = status
            status_row.health_message = message[:1000]
            for key, value in fields.items():
                setattr(status_row, key, value)
            db.commit()
            from app.services.ops_alert import mailbox_health_changed
            mailbox_health_changed(status_row.email_address, previous, status, message)
    except Exception as exc:
        logger.warning(f"[gmail_sync] Failed to update health status: {exc}")
        db.rollback()
    finally:
        db.close()


# ── Discovery (history.list) ──────────────────────────────────
def _history_message_ids(service, start_history_id: str) -> tuple[list[str], str]:
    """Message ids added to the Inbox since ``start_history_id``, and the latest historyId."""
    ids: list[str] = []
    latest = start_history_id
    page_token = None
    while True:
        response = service.users().history().list(
            userId="me",
            startHistoryId=start_history_id,
            historyTypes=["messageAdded"],
            labelId="INBOX",
            pageToken=page_token,
            maxResults=500,
        ).execute()
        for record in response.get("history", []):
            for added in record.get("messagesAdded", []):
                message = added.get("message", {})
                labels = set(message.get("labelIds", []))
                if "INBOX" in labels and not labels & _SKIP_LABELS:
                    ids.append(message["id"])
        latest = response.get("historyId", latest)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return list(dict.fromkeys(ids)), str(latest)


def _baseline_message_ids(service) -> tuple[list[str], str]:
    """Initial sync / history expired: current historyId + unread Inbox messages."""
    history_id = str(service.users().getProfile(userId="me").execute()["historyId"])
    ids: list[str] = []
    page_token = None
    for _ in range(10):  # at most 500 messages in a baseline
        response = service.users().messages().list(
            userId="me", q="is:unread in:inbox", maxResults=50, pageToken=page_token,
        ).execute()
        ids.extend(m["id"] for m in response.get("messages", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return ids, history_id


def _discover(service, history_id: str | None) -> tuple[list[str], str, bool]:
    from googleapiclient.errors import HttpError

    if history_id:
        try:
            ids, latest = _history_message_ids(service, history_id)
            return ids, latest, False
        except HttpError as exc:
            if getattr(exc.resp, "status", None) != 404:
                raise
            logger.warning("[gmail_sync] historyId expired; running a baseline resync")
    ids, latest = _baseline_message_ids(service)
    return ids, latest, True


async def sync_gmail_integration(integration_id: int) -> int:
    """Discover new messages for one Gmail mailbox and queue a job per message."""
    from app.jobs.queue import enqueue

    db = SessionLocal()
    try:
        integration = (
            db.query(EmailIntegration)
            .filter(
                EmailIntegration.id == integration_id,
                EmailIntegration.is_active == True,
                EmailIntegration.provider == "gmail",
            )
            .first()
        )
        if integration is None or integration.access_token is None:
            return 0
        history_id = integration.gmail_history_id
        recipient_addr = integration.email_address
    finally:
        db.close()

    try:
        service = await asyncio.to_thread(build_gmail_service, integration_id)
    except GmailAuthError as exc:
        logger.error(f"[gmail_sync] {recipient_addr}: {exc}")
        return 0

    try:
        message_ids, latest_history_id, baseline = await asyncio.to_thread(_discover, service, history_id)
    except Exception as exc:
        logger.error(f"[gmail_sync] Discovery failed for {recipient_addr}: {exc}")
        _update_health(integration_id, "error", f"Failed to list messages: {exc}")
        raise

    for gmail_msg_id in message_ids:
        await enqueue(
            "process_gmail_message", integration_id, gmail_msg_id,
            job_id=f"gmail:{integration_id}:{gmail_msg_id}",
        )

    # Advance the cursor only after every message has been queued.
    _update_health(
        integration_id, "healthy",
        f"Queued {len(message_ids)} message(s){' (baseline)' if baseline else ''}",
        len(message_ids), gmail_history_id=latest_history_id,
    )
    return len(message_ids)


# ── Per-message processing (runs as a job) ────────────────────
async def process_gmail_message(integration_id: int, gmail_msg_id: str) -> str:
    """Run the intake pipeline for one Gmail message. Idempotent."""
    from googleapiclient.errors import HttpError
    from app.services.document_intake.pipeline import process_document_intake_email

    db = SessionLocal()
    try:
        integration = db.query(EmailIntegration).filter(
            EmailIntegration.id == integration_id, EmailIntegration.is_active == True,
        ).first()
        if not integration:
            return "skipped"
        recipient_addr = integration.email_address
    finally:
        db.close()

    service = await asyncio.to_thread(build_gmail_service, integration_id)
    try:
        msg = await asyncio.to_thread(
            lambda: service.users().messages().get(userId="me", id=gmail_msg_id, format="full").execute()
        )
    except HttpError as exc:
        if getattr(exc.resp, "status", None) == 404:
            return "gone"  # deleted before we got to it
        raise

    labels = set(msg.get("labelIds", []))
    if labels & _SKIP_LABELS:
        return "skipped"

    ctx = build_intake_context_from_gmail(msg, recipient_addr)
    status = await process_document_intake_email(integration_id, service, ctx)

    # Emails from before the mailbox was connected are left untouched.
    if settings.GMAIL_MARK_PROCESSED_READ and status != "SKIPPED_OLD":
        await asyncio.to_thread(_mark_message_read, service, gmail_msg_id)
    return status


# ── Push notifications (users.watch) ──────────────────────────
def ensure_gmail_watch(integration_id: int) -> bool:
    """Start/renew the Gmail push subscription (expires after 7 days). Blocking."""
    if not settings.GMAIL_PUBSUB_TOPIC:
        return False
    db = SessionLocal()
    try:
        integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        expires = integration.gmail_watch_expires_at if integration else None
    finally:
        db.close()
    if expires and expires - datetime.now(timezone.utc) > timedelta(days=1):
        return False

    service = build_gmail_service(integration_id)
    response = service.users().watch(userId="me", body={
        "topicName": settings.GMAIL_PUBSUB_TOPIC,
        "labelIds": ["INBOX"],
        "labelFilterBehavior": "INCLUDE",
    }).execute()
    expiration = datetime.fromtimestamp(int(response["expiration"]) / 1000, tz=timezone.utc)
    db = SessionLocal()
    try:
        row = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if row:
            row.gmail_watch_expires_at = expiration
            if not row.gmail_history_id:
                row.gmail_history_id = str(response.get("historyId"))
            db.commit()
    finally:
        db.close()
    logger.info(f"[gmail_sync] Gmail watch active for integration {integration_id} until {expiration}")
    return True


# ── Sync all integrations ─────────────────────────────────────
async def sync_all_gmail():
    """Sync every active Gmail integration (used by manual triggers and the in-process poller)."""
    db = SessionLocal()
    try:
        integration_ids = [
            cast(int, row.id)
            for row in db.query(EmailIntegration.id).filter(
                EmailIntegration.is_active == True,
                EmailIntegration.provider == "gmail",
            )
        ]
    finally:
        db.close()

    total = 0
    for iid in integration_ids:
        try:
            total += await sync_gmail_integration(cast(int, iid))
        except Exception as exc:
            logger.exception(f"[gmail_sync] Integration {iid} sync failed: {exc}")
            _update_health(iid, "error", f"Sync failed: {exc}")

    if total:
        logger.info(f"[gmail_sync] Queued {total} new message(s) across all integrations")


# ── In-process scheduler (used when Redis/ARQ is unavailable) ─
async def start_email_poller():
    """Fallback scheduler: runs the same periodic jobs the ARQ cron would."""
    from app.jobs.tasks import run_periodic_maintenance, schedule_mailbox_syncs

    logger.info(f"[gmail_sync] In-process poller started — interval={settings.FETCH_INTERVAL_SECONDS}s")
    try:
        while True:
            try:
                await schedule_mailbox_syncs(force=True)
                await run_periodic_maintenance()
            except Exception as exc:
                logger.error(f"[gmail_sync] Poller cycle failed: {exc}")
            await asyncio.sleep(settings.FETCH_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("[gmail_sync] Email poller stopped")
        raise
