"""
Gmail sync service.
Polls all active Gmail integrations every FETCH_INTERVAL_SECONDS,
saves new emails to the DB, and triggers the AI analysis pipeline.
"""
from __future__ import annotations

import asyncio
import base64
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, cast

from loguru import logger
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database import SessionLocal
from app.models.email import Email, EmailIntegration, AllowedDomain
from app.utils.crypto import decrypt_token, encrypt_token

# Cap concurrent AI-pipeline tasks so we never hold more than this
# many DB connections simultaneously for analysis work.
_analysis_semaphore = asyncio.Semaphore(3)


def _mark_message_read(service, msg_id: str) -> None:
    """Best-effort: remove UNREAD label so blocked messages are not reprocessed forever."""
    try:
        service.users().messages().modify(
            userId="me",
            id=msg_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()
    except Exception as exc:
        logger.warning(f"[gmail_sync] Failed to mark blocked message {msg_id} as read: {exc}")


def _is_automated_or_self_message(
    headers: dict[str, str],
    sender_email: str,
    recipient_email: str,
) -> bool:
    """Identify messages that should not receive an automated rejection reply."""
    sender = sender_email.strip().lower()
    recipient = recipient_email.strip().lower()
    if sender and recipient and sender == recipient:
        return True

    normalized_headers = {
        key.strip().lower(): str(value).strip().lower()
        for key, value in headers.items()
    }
    return any(
        normalized_headers.get(header, "") in values
        for header, values in {
            "auto-submitted": {"auto-generated", "auto-replied", "auto-notified"},
            "precedence": {"bulk", "junk", "list"},
            "x-auto-response-suppress": {"all", "auto-reply"},
        }.items()
    )


# ── Body extraction ───────────────────────────────────────────

def _extract_gmail_body(payload: dict) -> tuple[str, str]:
    """Recursively extract plain-text and HTML body from a Gmail API payload."""
    plain, html = "", ""
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            plain = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    elif mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    elif "parts" in payload:
        for part in payload["parts"]:
            p, h = _extract_gmail_body(part)
            plain = plain or p
            html = html or h

    return plain, html


# ── Per-integration sync ──────────────────────────────────────
async def sync_gmail_integration(integration_id: int) -> int:
    """
    Fetch unread emails for one Gmail integration.
    Saves new emails to DB, marks Gmail messages as read,
    and queues AI analysis.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    # ---------------------------------------------------------
    # Load integration
    # ---------------------------------------------------------
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

        access_token = decrypt_token(cast(str | None, integration.access_token))
        refresh_token = decrypt_token(cast(str | None, integration.refresh_token))
        recipient_addr = cast(str, integration.email_address)
        integration_pk = cast(int, integration.id)
        configured_processing_mode = cast(str | None, integration.processing_mode)
        processing_mode = configured_processing_mode or "conversation"
        conversation_analysis_enabled = (
            cast(bool, integration.conversation_analysis_enabled)
            if integration.conversation_analysis_enabled is not None
            else True
        )

    finally:
        db.close()

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GMAIL_CLIENT_ID,
        client_secret=settings.GMAIL_CLIENT_SECRET,
        scopes=[
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )

    # ---------------------------------------------------------
    # Refresh token
    # ---------------------------------------------------------
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())

            db2 = SessionLocal()
            try:
                row = (
                    db2.query(EmailIntegration)
                    .filter(EmailIntegration.id == integration_pk)
                    .first()
                )

                if row:
                    setattr(row, "access_token", encrypt_token(creds.token))
                    db2.commit()

            finally:
                db2.close()

            logger.info(
                f"[gmail_sync] Token refreshed for {recipient_addr}"
            )

        except Exception as exc:
            logger.error(
                f"[gmail_sync] Token refresh failed for {recipient_addr}: {exc}"
            )
            return 0

    # ---------------------------------------------------------
    # Gmail service
    # ---------------------------------------------------------
    try:
        service = build(
            "gmail",
            "v1",
            credentials=creds,
            cache_discovery=False,
        )
    except Exception as exc:
        logger.error(
            f"[gmail_sync] Failed to build Gmail service: {exc}"
        )
        return 0

    # ---------------------------------------------------------
    # Load whitelist once
    # ---------------------------------------------------------
    db_domains = SessionLocal()
    try:
        allowed_domains = {
            d.domain.lower().strip()
            for d in db_domains.query(AllowedDomain)
            .filter(AllowedDomain.is_active == True)
            .all()
        }
    finally:
        db_domains.close()

    # ---------------------------------------------------------
    # Fetch unread emails
    # ---------------------------------------------------------
    try:
        result = (
            service.users()
            .messages()
            .list(
                userId="me",
                q="is:unread in:inbox",
                maxResults=50,
            )
            .execute()
        )
    except Exception as exc:
        logger.error(
            f"[gmail_sync] Failed to fetch unread messages: {exc}"
        )
        return 0

    messages = result.get("messages", [])

    if not messages:
        return 0

    new_count = 0
    new_email_ids: list[int] = []

    for msg_meta in messages:
        gmail_msg_id = msg_meta["id"]

        # -----------------------------------------------------
        # Fetch full message
        # -----------------------------------------------------
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=gmail_msg_id,
                    format="full",
                )
                .execute()
            )

        except Exception as exc:
            logger.warning(
                f"[gmail_sync] Failed to fetch message {gmail_msg_id}: {exc}"
            )
            continue

        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }

        subject = headers.get("Subject", "(no subject)")
        from_raw = headers.get("From", "")
        date_str = headers.get("Date", "")
        thread_id = msg.get("threadId")

        message_id_header = (
            headers.get("Message-ID", "")
            .strip()
            .strip("<>")
        )

        stored_message_id = (
            message_id_header or gmail_msg_id
        )

        sender_name, sender_email = (
            parseaddr(from_raw)
        )

        sender_domain = (
            sender_email.split("@")[-1].lower()
            if "@" in sender_email
            else ""
        )

        # -----------------------------------------------------
        # Document-intake pipeline branch (§1.1: processing_mode)
        # Runs independently of the conversational flow below;
        # for "document_intake"-only integrations we skip creating
        # the conversational Email row entirely for this message.
        # -----------------------------------------------------
        if processing_mode in ("document_intake", "both"):
            try:
                received_at_for_intake = parsedate_to_datetime(date_str)
            except Exception:
                received_at_for_intake = datetime.now(timezone.utc)

            plain_for_intake, _html_for_intake = _extract_gmail_body(msg.get("payload", {}))
            intake_headers = dict(headers)
            intake_headers["_body_plain"] = plain_for_intake

            from app.services.document_intake.pipeline import (
                process_document_intake_email, IntakeEmailContext,
            )

            ctx = IntakeEmailContext(
                gmail_message_id=gmail_msg_id,
                stored_message_id=stored_message_id,
                thread_id=thread_id,
                headers=intake_headers,
                sender_name=sender_name,
                sender_email=sender_email,
                recipient_email=recipient_addr,
                subject=subject,
                received_at=received_at_for_intake,
                payload=msg.get("payload", {}),
            )

            try:
                await process_document_intake_email(integration_pk, service, ctx)
            except Exception as exc:
                logger.error(f"[gmail_sync] Document intake pipeline failed for {gmail_msg_id}: {exc}")

            # The pipeline has durably created or found the batch. Do this even
            # for a failed terminal status so the same unread message is not
            # submitted on every polling cycle.
            _mark_message_read(service, gmail_msg_id)

            if processing_mode == "document_intake":
                continue

        # -----------------------------------------------------
        # Duplicate check
        # -----------------------------------------------------
        db_check = SessionLocal()
        try:
            existing_email = (
                db_check.query(Email)
                .filter(
                    Email.message_id == stored_message_id
                )
                .first()
            )

            if existing_email:
                _mark_message_read(
                    service,
                    gmail_msg_id,
                )
                continue

        finally:
            db_check.close()

        # -----------------------------------------------------
        # Domain whitelist
        # -----------------------------------------------------
        is_allowed = (
            not allowed_domains
            or sender_domain in allowed_domains
        )

        if not is_allowed:

            logger.info(
                f"[gmail_sync] Blocked email from "
                f"{sender_email} ({sender_domain})"
            )

            sender_lower = sender_email.lower()

            is_system_sender = _is_automated_or_self_message(
                headers,
                sender_email,
                recipient_addr,
            ) or (
                sender_lower.startswith("mailer-daemon")
                or sender_lower.startswith("postmaster")
                or "noreply" in sender_lower
                or "no-reply" in sender_lower
                or sender_domain in {
                    "google.com",
                    "googlemail.com",
                    "accounts.google.com",
                }
            )

            if not is_system_sender:
                try:
                    _send_domain_rejection(
                        service,
                        sender_email,
                        recipient_addr,
                        subject,
                        thread_id,
                        message_id_header,
                    )
                except Exception as exc:
                    logger.warning(
                        f"[gmail_sync] Auto-reply failed: {exc}"
                    )

            _mark_message_read(
                service,
                gmail_msg_id,
            )
            continue

        # -----------------------------------------------------
        # Parse date/body
        # -----------------------------------------------------
        try:
            received_at = (
                parsedate_to_datetime(
                    date_str
                )
            )
        except Exception:
            received_at = datetime.now(
                timezone.utc
            )

        plain, html = _extract_gmail_body(
            msg.get("payload", {})
        )

        # -----------------------------------------------------
        # Save email
        # -----------------------------------------------------
        db_email = SessionLocal()

        try:
            email_obj = Email(
                message_id=stored_message_id,
                integration_id=integration_pk,
                subject=subject,
                sender_name=sender_name,
                sender_email=sender_email,
                recipient_email=recipient_addr,
                body_plain=plain,
                body_html=html,
                received_at=received_at,
                thread_id=thread_id,
            )

            db_email.add(email_obj)
            db_email.commit()
            db_email.refresh(email_obj)

            try:
                _mark_message_read(service, gmail_msg_id)
            except Exception as exc:
                logger.warning(
                    f"[gmail_sync] Failed to mark {gmail_msg_id} read: {exc}"
                )

            new_email_ids.append(
                cast(int, email_obj.id)
            )
            new_count += 1

            logger.info(
                f"[gmail_sync] Saved email "
                f"'{subject[:60]}' "
                f"from {sender_email}"
            )

        except IntegrityError:
            db_email.rollback()

            try:
                _mark_message_read(
                    service,
                    gmail_msg_id,
                )
            except Exception:
                pass

            logger.info(
                f"[gmail_sync] Duplicate email skipped: "
                f"{stored_message_id}"
            )

        except Exception as exc:
            db_email.rollback()

            logger.error(
                f"[gmail_sync] Failed to save email "
                f"{gmail_msg_id}: {exc}"
            )

        finally:
            db_email.close()

    # ---------------------------------------------------------
    # Queue AI analysis
    # ---------------------------------------------------------
    _queue_analysis_if_enabled(new_email_ids, conversation_analysis_enabled)

    status_db = SessionLocal()
    try:
        row = status_db.query(EmailIntegration).filter(EmailIntegration.id == integration_pk).first()
        if row:
            status_row = cast(Any, row)
            status_row.last_sync_at = datetime.now(timezone.utc)
            if new_count:
                status_row.last_email_processed_at = datetime.now(timezone.utc)
            status_row.health_status = "healthy"
            status_row.health_message = f"Fetched {new_count} new email(s)"
            status_db.commit()
    except Exception as exc:
        logger.warning(f"[gmail_sync] Failed to update health status: {exc}")
        status_db.rollback()
    finally:
        status_db.close()
    return new_count


def _send_domain_rejection(
    service,
    sender_addr: str,
    my_addr: str,
    subject: str,
    thread_id: str | None,
    message_id_header: str | None,
):
    """Send an auto-reply via Gmail API telling the sender they are not allowed."""
    import email as _email_lib
    from email.mime.text import MIMEText

    body = (
        f"Hello,\n\n"
        f"Thank you for your email. Unfortunately your domain is not authorised to "
        f"send messages to this mailbox, so your message could not be delivered.\n\n"
        f"If you believe this is an error, please contact the mailbox administrator.\n\n"
        f"This is an automated response — please do not reply to this message."
    )
    msg = MIMEText(body)
    msg["To"]      = sender_addr
    msg["From"]    = my_addr
    msg["Subject"] = f"Re: {subject}"
    if thread_id and message_id_header:
        msg["In-Reply-To"] = message_id_header
        msg["References"] = message_id_header

    import base64 as _b64
    raw = _b64.urlsafe_b64encode(msg.as_bytes()).decode()
    send_body: dict = {"raw": raw}
    if thread_id:
        send_body["threadId"] = thread_id

    try:
        service.users().messages().send(userId="me", body=send_body).execute()
        logger.info(
            f"[gmail_sync] Domain rejection auto-reply sent to {sender_addr}"
        )

    except Exception as exc:
        if "rateLimitExceeded" in str(exc):
            logger.warning(
                "[gmail_sync] Gmail send limit exceeded"
            )
        else:
            logger.warning(
                f"[gmail_sync] Failed to send domain rejection reply: {exc}"
            )


def _schedule_analysis(email_id):
    """Fire-and-forget: queue the AI analysis pipeline for a newly saved email.

    The semaphore ensures at most 3 pipelines run concurrently, keeping
    DB connection usage well within pool limits.
    The pipeline itself manages its own short-lived DB sessions.
    """
    from app.routers.emails import _run_analysis_pipeline

    async def _run():
        async with _analysis_semaphore:
            try:
                await _run_analysis_pipeline(email_id)
            except Exception as exc:
                logger.error(f"[gmail_sync] Analysis failed for email {email_id}: {exc}")

    asyncio.create_task(_run())


def _queue_analysis_if_enabled(email_ids: list[int], enabled: bool | None) -> None:
    """Queue conversational analysis only when the mailbox has it enabled."""
    if enabled is not False:
        for email_id in email_ids:
            _schedule_analysis(email_id)


# ── Sync all integrations ─────────────────────────────────────

async def sync_all_gmail():
    """Sync every active Gmail integration."""
    db = SessionLocal()
    try:
        integration_ids = [
            cast(int, row.id)
            for row in db.query(EmailIntegration).filter(
                EmailIntegration.is_active == True,
                EmailIntegration.provider == "gmail",
            )
        ]
    finally:
        db.close()

    total = 0
    for iid in integration_ids:
        total += await sync_gmail_integration(cast(int, iid))

    if total:
        logger.info(f"[gmail_sync] Fetched {total} new email(s) across all integrations")


# ── Background poller ─────────────────────────────────────────
async def start_email_poller():
    logger.info(
        f"[gmail_sync] Email poller started — "
        f"interval={settings.FETCH_INTERVAL_SECONDS}s"
    )

    try:
        while True:
            try:
                await sync_all_gmail()
                from app.services.document_intake.provider_sync import sync_all_document_providers
                await sync_all_document_providers()
            except Exception as exc:
                logger.error(
                    f"[gmail_sync] Poller cycle failed: {exc}"
                )

            await asyncio.sleep(
                settings.FETCH_INTERVAL_SECONDS
            )

    except asyncio.CancelledError:
        logger.info(
            "[gmail_sync] Email poller stopped"
        )
        raise