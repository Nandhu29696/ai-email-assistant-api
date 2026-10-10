"""
Email intake pipeline — the one flow every new email goes through.

  0. Picked up automatically (mailbox sync job).
     Machine-sent mail (bounces, out-of-office, newsletters) is recorded and ignored;
     forged senders (SPF/DKIM/DMARC failure) are rejected without a reply.
  1. Sender domain not allowed      -> reply "domain not valid"             -> REJECTED
  2. Domain allowed                 -> reply "received, status shortly"
  3. No attachment                  -> reply "no attachment, please upload" -> REJECTED
     Any attachment of a type that is not allowed (or too large)
                                    -> reply listing those files            -> REJECTED
  4. Every attachment is opened; password-protected, encrypted or unreadable files
                                    -> reply listing those files            -> REJECTED
  5. Valid attachments: the email is analysed (category, sentiment, emotion, priority,
     summary — only emails that passed every rule), each attachment converted to PDF and stored (5.1), the email content
     rendered as a PDF (5.2), everything merged with the email PDF last (5.3),
     the merged PDF stored and a success reply listing the attachments sent (5.4)
                                    -> SUCCESS (5.5)

A system problem (converter missing, storage error) ends as FAILED without
blaming the sender; an admin can reprocess the email once it is fixed.

Blocking work (provider API calls, LibreOffice, PDF processing, storage) runs
in worker threads so the event loop stays responsive.
"""
from __future__ import annotations

import asyncio
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.document_intake import EmailBatch, EmailBatchAttachment, EmailBatchEvent
from app.models.email import EmailIntegration
from app.services.ai_client import ai_available, get_model
from app.services.classifier import classify_email
from app.services.document_intake.attachment_extractor import (
    extract_attachments_from_gmail_payload, has_attachments,
)
from app.services.document_intake.attachment_validator import PROTECTED, check_attachment
from app.services.document_intake.batch_id_generator import generate_batch_no
from app.services.document_intake.conversion.doc_to_pdf import (
    ConverterUnavailableError, DocConversionError, convert_doc_to_pdf,
)
from app.services.document_intake.conversion.pdf_passthrough import convert_pdf_passthrough
from app.services.document_intake.conversion.tiff_to_pdf import convert_tiff_to_pdf
from app.services.document_intake.domain_validator import validate_domain
from app.services.document_intake.file_policy_validator import validate_file_policy
from app.services.document_intake.mailbox_folder_service import move_to_failed, move_to_success
from app.services.document_intake.pdf_merger import EmailMetadataForTrailer, build_email_pdf, merge_pdfs
from app.services.document_intake.sender_checks import is_automated_message, sender_authentication_failed
from app.services.document_intake.storage.factory import get_storage_adapter
from app.services.document_intake.template_renderer import file_list_html, render_template
from app.services.emotion_detector import detect_emotions
from app.services.preprocessor import preprocess_email
from app.services.priority_assigner import assign_priority
from app.services.summarizer import generate_summary
from app.services.sentiment_analyzer import analyze_sentiment

# Batch statuses
RECEIVED, PROCESSING = "RECEIVED", "PROCESSING"
SUCCESS, REJECTED, FAILED, IGNORED = "SUCCESS", "REJECTED", "FAILED", "IGNORED"
FINAL_STATUSES = (SUCCESS, REJECTED, FAILED, IGNORED)


class _SystemError(Exception):
    """A problem on our side; the sender is not told the email was bad."""


@dataclass
class IntakeEmailContext:
    """Pre-parsed email fields (built by the provider sync for Gmail, Outlook or IMAP)."""
    gmail_message_id: str          # provider message id (Gmail id / Graph id / IMAP UID)
    stored_message_id: str         # RFC Message-ID, used for de-duplication
    thread_id: str | None
    headers: dict[str, str]        # "_body_plain" carries the plain-text body
    sender_name: str
    sender_email: str
    recipient_email: str
    subject: str
    received_at: datetime
    payload: dict

    @property
    def body_text(self) -> str:
        return self.headers.get("_body_plain", "") or ""


# ── Small helpers ─────────────────────────────────────────────
async def _slow(db: Session, fn, *args):
    """Run blocking work (provider API, LibreOffice, PDF, storage) in a thread without holding a DB connection.

    Committing first returns the connection to the pool, so a database that drops
    idle connections quickly (e.g. MySQL wait_timeout=20s) cannot break the email
    while a slow step runs.
    """
    db.commit()
    return await asyncio.to_thread(fn, *args)


def _log_event(
    db: Session,
    batch: EmailBatch,
    event_type: str,
    related_filename: str | None = None,
    details: dict | None = None,
    reply_sent: bool = False,
) -> None:
    db.add(EmailBatchEvent(
        parent_batch_id=batch.id,
        batch_no=batch.batch_no,
        event_type=event_type,
        related_filename=related_filename,
        reply_sent=reply_sent,
        details=details or {},
    ))
    db.commit()


def _finish(db: Session, batch: EmailBatch, status: str, outcome: str, reason: str) -> str:
    batch.status = status
    batch.outcome = outcome
    batch.status_reason = reason[:2000]
    batch.processed_at = datetime.now(timezone.utc)
    db.commit()
    return status


def _allowed_extensions(integration: EmailIntegration) -> str:
    return integration.allowed_extensions or settings.DOCUMENT_INTAKE_DEFAULT_ALLOWED_EXTENSIONS


def _max_file_size_mb(integration: EmailIntegration) -> int:
    return integration.max_file_size_mb or settings.DOCUMENT_INTAKE_DEFAULT_MAX_FILE_SIZE_MB


def _pretty_extensions(csv: str) -> str:
    return ", ".join(f".{e.strip().lstrip('.')}" for e in csv.split(",") if e.strip())


def _safe_name(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:80] or "attachment"


def _storage_folder(integration: EmailIntegration, batch: EmailBatch) -> str:
    received = batch.received_datetime or datetime.now(timezone.utc)
    # Forward slashes so blob names are identical on every OS.
    return posixpath.join(
        (integration.mailbox_type or "PROD").upper(),
        received.strftime("%Y"), received.strftime("%m"), batch.batch_no,
    )


# ── Replies ───────────────────────────────────────────────────
MAX_STORED_REPLY_CHARS = 20_000

def _send_rendered(service, ctx: IntakeEmailContext, subject: str, html_body: str) -> bool:
    """Blocking send of a rendered HTML auto-reply via the provider (in the same thread)."""
    if hasattr(service, "send_reply"):
        return bool(service.send_reply(ctx, subject, html_body))

    import base64
    from email.mime.text import MIMEText
    from app.services.gmail_client import format_message_id

    msg = MIMEText(html_body, "html", "utf-8")
    msg["To"] = ctx.sender_email
    msg["From"] = ctx.recipient_email
    msg["Subject"] = subject
    msg["Auto-Submitted"] = "auto-replied"
    lower_headers = {k.lower(): v for k, v in ctx.headers.items()}
    message_id = format_message_id(lower_headers.get("message-id"))
    if message_id:
        msg["In-Reply-To"] = message_id
        msg["References"] = message_id

    send_body: dict = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if ctx.thread_id:
        send_body["threadId"] = ctx.thread_id
    service.users().messages().send(userId="me", body=send_body).execute()
    return True


async def _reply(
    db: Session,
    service,
    ctx: IntakeEmailContext,
    integration: EmailIntegration,
    batch: EmailBatch,
    template_key: str,
    event_type: str,
    context: dict | None = None,
    details: dict | None = None,
) -> bool:
    """Render a rule's template, send it in the sender's thread and log the event (with what was sent)."""
    sent, error, rendered = False, None, None
    try:
        rendered = render_template(
            db, template_key,
            context={
                "subject": ctx.subject,
                "batch_no": batch.batch_no,
                "allowed_extensions": _pretty_extensions(_allowed_extensions(integration)),
                "max_file_size_mb": _max_file_size_mb(integration),
                **(context or {}),
            },
            integration_id=integration.id,
        )
        sent = await _slow(db, _send_rendered, service, ctx, rendered.subject, rendered.html_body)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:500]
        logger.warning(f"[intake] {template_key} reply to {ctx.sender_email} failed: {error}")
    event_details = dict(details or {})
    event_details["template"] = template_key
    event_details["reply_to"] = ctx.sender_email
    if rendered is not None:
        # Kept so the email's details can show exactly what the sender received.
        event_details["reply_subject"] = rendered.subject[:500]
        event_details["reply_html"] = rendered.html_body[:MAX_STORED_REPLY_CHARS]
    if error:
        event_details["reply_error"] = error
    _log_event(db, batch, event_type, details=event_details, reply_sent=sent)
    return sent


# ── Mailbox folder move ───────────────────────────────────────
def _move_message(service, integration: EmailIntegration, message_id: str, success: bool) -> bool:
    label = (integration.success_folder_label or "Processed/Success") if success else (
        integration.failed_folder_label or "Processed/Failed"
    )
    if not service or not message_id:
        return False
    if hasattr(service, "move_to_success"):
        return bool(service.move_to_success(message_id, label) if success else service.move_to_failed(message_id, label))
    return move_to_success(service, message_id, label) if success else move_to_failed(service, message_id, label)


async def _file_away(db: Session, batch: EmailBatch, integration: EmailIntegration, service, ctx) -> None:
    """Move the source email to Processed/Success or Processed/Failed (best effort)."""
    if batch.status not in (SUCCESS, REJECTED):
        return
    try:
        moved = await _slow(db, _move_message, service, integration, ctx.gmail_message_id, batch.status == SUCCESS)
        if not moved:
            _log_event(db, batch, "EMAIL_MOVE_SKIPPED")
    except Exception as exc:
        logger.warning(f"[intake] Mailbox move failed for {batch.batch_no}: {exc}")
        _log_event(db, batch, "EMAIL_MOVE_FAILED", details={"error": str(exc)[:500]})


# ── Batch bookkeeping ─────────────────────────────────────────
def _prepare_batch(
    db: Session,
    integration: EmailIntegration,
    ctx: IntakeEmailContext,
    reprocess_batch_id: int | None,
) -> tuple[EmailBatch | None, str | None]:
    """Create the batch row, or reset an existing one for reprocessing.

    Returns ``(batch, None)`` to proceed, or ``(None, status)`` for duplicates.
    """
    if reprocess_batch_id is not None:
        existing = db.query(EmailBatch).filter(
            EmailBatch.id == reprocess_batch_id, EmailBatch.integration_id == integration.id,
        ).first()
    else:
        existing = db.query(EmailBatch).filter(
            EmailBatch.integration_id == integration.id,
            EmailBatch.message_id == ctx.stored_message_id,
        ).first()
    if existing and existing.id != reprocess_batch_id:
        logger.info(f"[intake] Skipping duplicate message {ctx.stored_message_id} for mailbox {integration.id}")
        return None, existing.status or RECEIVED

    if existing:
        # Manual reprocess: clear per-attachment state but keep the audit trail.
        db.query(EmailBatchAttachment).filter(EmailBatchAttachment.parent_batch_id == existing.id).delete()
        existing.status = RECEIVED
        existing.outcome = None
        existing.status_reason = "Reprocessing"
        existing.processed_at = None
        existing.attachment_count = 0
        existing.email_pdf_path = None
        existing.merged_pdf_path = None
        existing.is_archived = False
        existing.archived_at = None
        db.commit()
        _log_event(db, existing, "REPROCESS_STARTED")
        return existing, None

    batch = EmailBatch(
        batch_no=generate_batch_no(db, integration.batch_prefix, integration.mailbox_type),
        message_id=ctx.stored_message_id,
        conversation_id=ctx.gmail_message_id,
        integration_id=integration.id,
        mailbox_type=integration.mailbox_type,
        sender_name=(ctx.sender_name or "")[:255] or None,
        sender_email=ctx.sender_email or "(unknown)",
        recipient_email=ctx.recipient_email,
        subject=ctx.subject,
        body_text=ctx.body_text[:100_000],
        received_datetime=ctx.received_at,
        status=RECEIVED,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    _log_event(db, batch, "RECEIVED", details={"from": ctx.sender_email})
    return batch, None


def _is_before_cutoff(integration: EmailIntegration, ctx: IntakeEmailContext) -> bool:
    cutoff = integration.process_since
    if not cutoff or not ctx.received_at:
        return False
    received = ctx.received_at if ctx.received_at.tzinfo else ctx.received_at.replace(tzinfo=timezone.utc)
    cutoff = cutoff if cutoff.tzinfo else cutoff.replace(tzinfo=timezone.utc)
    return received < cutoff


# ── Entry point ───────────────────────────────────────────────
async def process_document_intake_email(
    integration_id: int,
    service,
    ctx: IntakeEmailContext,
    reprocess_batch_id: int | None = None,
) -> str:
    """Run the full flow for one inbound email. Returns the final batch status."""
    db = SessionLocal()
    batch: EmailBatch | None = None
    try:
        integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if not integration:
            logger.error(f"[intake] Mailbox {integration_id} not found")
            return FAILED
        if reprocess_batch_id is None and _is_before_cutoff(integration, ctx):
            logger.info(f"[intake] Skipping {ctx.stored_message_id}: received before the mailbox was connected")
            return "SKIPPED_OLD"

        batch, duplicate_status = _prepare_batch(db, integration, ctx, reprocess_batch_id)
        if batch is None:
            return duplicate_status or RECEIVED

        try:
            status = await _run_rules(db, integration, service, ctx, batch)
        except _SystemError as exc:
            db.rollback()
            _log_event(db, batch, "SYSTEM_ERROR", details={"error": str(exc)[:1000]})
            status = _finish(db, batch, FAILED, "SYSTEM_ERROR", str(exc))
        except Exception as exc:
            # Never leave a batch stuck in RECEIVED/PROCESSING: record it so it can be reprocessed.
            logger.exception(f"[intake] Unexpected failure for {batch.batch_no}: {exc}")
            db.rollback()
            _log_event(db, batch, "SYSTEM_ERROR", details={"error": f"{type(exc).__name__}: {exc}"[:1000]})
            status = _finish(db, batch, FAILED, "SYSTEM_ERROR", f"Processing error: {type(exc).__name__}")
        await _file_away(db, batch, integration, service, ctx)
        _touch_mailbox(db, integration)
        if status == FAILED:
            from app.services.ops_alert import alert_email_needs_attention
            await _slow(db, 
                alert_email_needs_attention, batch.batch_no, batch.sender_email, batch.subject, batch.status_reason,
            )
        return status
    finally:
        db.close()


def _touch_mailbox(db: Session, integration: EmailIntegration) -> None:
    try:
        integration.last_email_processed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()


async def _analyse(db: Session, batch: EmailBatch, ctx: IntakeEmailContext) -> None:
    """Categorise the email and analyse its sentiment/emotion (step 0)."""
    text = preprocess_email(ctx.body_text, None) or ""
    text_with_subject = f"{ctx.subject}\n\n{text}".strip()
    try:
        sentiment = analyze_sentiment(text_with_subject)
        emotions = detect_emotions(text_with_subject)
        db.commit()   # no DB connection is held while the AI model works
        classification = await classify_email(text_with_subject)
        batch.sentiment = sentiment.label
        batch.sentiment_score = sentiment.score
        batch.primary_emotion = emotions.primary_emotion
        batch.email_category = classification.category
        batch.priority = assign_priority(
            sentiment.label, float(sentiment.score), emotions.primary_emotion, classification.category,
        ).priority
        db.commit()   # release the connection before the (possibly slow) summary call
        if settings.AI_SUMMARY_ENABLED:
            batch.ai_summary = (await generate_summary(ctx.subject, text))[:2000]
        batch.ai_model_version = get_model() if ai_available() else "rules-engine"
        db.commit()
        _log_event(db, batch, "ANALYZED", details={
            "category": batch.email_category, "sentiment": batch.sentiment,
            "emotion": batch.primary_emotion, "priority": batch.priority,
        })
    except Exception as exc:
        db.rollback()
        logger.warning(f"[intake] AI analysis failed for {batch.batch_no}: {exc}")
        _log_event(db, batch, "ANALYSIS_FAILED", details={"error": str(exc)[:500]})


def _ack_already_sent(db: Session, batch: EmailBatch) -> bool:
    return db.query(EmailBatchEvent.id).filter(
        EmailBatchEvent.parent_batch_id == batch.id,
        EmailBatchEvent.event_type == "ACKNOWLEDGEMENT_SENT",
        EmailBatchEvent.reply_sent == True,
    ).first() is not None


def _convert(doc_type: str, data: bytes, filename: str) -> bytes:
    if doc_type == "pdf":
        return convert_pdf_passthrough(data)
    if doc_type in ("doc", "docx"):
        return convert_doc_to_pdf(data, filename)
    if doc_type in ("tiff", "tif"):
        return convert_tiff_to_pdf(data)
    raise DocConversionError(f"Files of type .{doc_type} cannot be converted")


async def _run_rules(
    db: Session,
    integration: EmailIntegration,
    service,
    ctx: IntakeEmailContext,
    batch: EmailBatch,
) -> str:
    batch.status = PROCESSING
    batch.status_reason = "Processing"
    db.commit()

    if is_automated_message(ctx.headers, ctx.sender_email):
        _log_event(db, batch, "AUTOMATED_MESSAGE_IGNORED")
        return _finish(db, batch, IGNORED, "AUTOMATED_MESSAGE",
                       "Automated message (bounce, out-of-office or mailing list) — no reply sent")
    if sender_authentication_failed(ctx.headers):
        _log_event(db, batch, "SENDER_NOT_VERIFIED")
        return _finish(db, batch, REJECTED, "SENDER_NOT_VERIFIED",
                       "Sender could not be verified (SPF/DKIM/DMARC failed) — not processed, no reply sent")

    # ── 1. Sender domain ────────────────────────────────────
    domain_check = validate_domain(db, ctx.sender_email, integration)
    if not domain_check.is_allowed:
        await _reply(db, service, ctx, integration, batch, "domain_rejected", "DOMAIN_REJECTED",
                     {"domain": domain_check.domain}, {"domain": domain_check.domain})
        return _finish(db, batch, REJECTED, "DOMAIN_NOT_ALLOWED", domain_check.reason)

    # ── 2. Acknowledgement ──────────────────────────────────
    if not _ack_already_sent(db, batch):
        await _reply(db, service, ctx, integration, batch, "acknowledgement", "ACKNOWLEDGEMENT_SENT")

    # ── 3. Attachments present and of an allowed type ───────
    if hasattr(service, "has_attachments"):
        present = await _slow(db, service.has_attachments, ctx)
    else:
        present = has_attachments(ctx.payload)
    extracted = []
    if present:
        if hasattr(service, "extract_attachments"):
            extracted = await _slow(db, service.extract_attachments, ctx)
        else:
            extracted = await _slow(db, 
                extract_attachments_from_gmail_payload, service, ctx.gmail_message_id, ctx.payload,
            )
    if not extracted:
        await _reply(db, service, ctx, integration, batch, "no_attachment", "NO_ATTACHMENT")
        return _finish(db, batch, REJECTED, "NO_ATTACHMENT", "The email has no attachment to process")

    batch.attachment_count = len(extracted)
    rows: list[EmailBatchAttachment] = []
    for att in extracted:
        row = EmailBatchAttachment(
            parent_batch_id=batch.id,
            batch_no=batch.batch_no,
            batch_source_filename=att.filename[:255],
            doc_type=att.filename.rsplit(".", 1)[-1].lower()[:20] if "." in att.filename else "",
            file_size_bytes=att.size_bytes,
            received_date=ctx.received_at,
            status="PENDING",
        )
        db.add(row)
        rows.append(row)
    db.commit()

    allowed = _allowed_extensions(integration)
    max_mb = _max_file_size_mb(integration)
    unsupported: list[tuple[str, str]] = []
    for att, row in zip(extracted, rows):
        policy = validate_file_policy(att.filename, att.size_bytes, allowed, max_mb)
        if not policy.is_allowed:
            row.status = "INVALID_TYPE"
            row.status_reason = policy.reason
            unsupported.append((att.filename, policy.reason))
    if unsupported:
        for row in rows:
            if row.status == "PENDING":
                row.status = "NOT_PROCESSED"
                row.status_reason = "Not processed because other attachments are not supported"
        db.commit()
        await _reply(db, service, ctx, integration, batch, "invalid_file_type", "INVALID_FILE_TYPE",
                     {"file_list_html": file_list_html(unsupported)},
                     {"files": [name for name, _ in unsupported]})
        return _finish(db, batch, REJECTED, "INVALID_FILE_TYPE",
                       "Unsupported attachment(s): " + ", ".join(name for name, _ in unsupported))
    db.commit()

    # ── 4. Every attachment must open (and convert) ─────────
    invalid: list[tuple[str, str]] = []
    converted: list[tuple[EmailBatchAttachment, bytes]] = []
    for att, row in zip(extracted, rows):
        check = await _slow(db, check_attachment, att.filename, att.data)
        if not check.ok:
            row.status = check.status          # PROTECTED | UNREADABLE
            row.is_encrypted = check.status == PROTECTED
            row.status_reason = check.reason
            invalid.append((att.filename, check.reason))
            continue
        try:
            pdf = await _slow(db, _convert, row.doc_type, att.data, att.filename)
        except ConverterUnavailableError as exc:
            raise _SystemError(f"Cannot convert {att.filename}: {exc}") from exc
        except Exception as exc:
            logger.info(f"[intake] {att.filename} could not be converted: {exc}")
            row.status = "UNREADABLE"
            row.status_reason = "The file could not be opened for conversion"
            invalid.append((att.filename, row.status_reason))
            continue
        converted.append((row, pdf))
    db.commit()

    if invalid:
        for row, _pdf in converted:
            row.status = "NOT_PROCESSED"
            row.status_reason = "Not processed because other attachments could not be opened"
        db.commit()
        await _reply(db, service, ctx, integration, batch, "invalid_attachments", "INVALID_ATTACHMENTS",
                     {"file_list_html": file_list_html(invalid)},
                     {"files": [name for name, _ in invalid]})
        return _finish(db, batch, REJECTED, "INVALID_ATTACHMENTS",
                       "Attachment(s) protected or unreadable: " + ", ".join(name for name, _ in invalid))

    # ── AI analysis: only for emails that passed every rule ──
    # Ignored and rejected emails are not analysed. The summary is ready in
    # time to be printed on the email-content PDF (5.2).
    await _analyse(db, batch, ctx)

    # ── 5. Convert -> store -> email PDF -> merge -> store ──
    adapter = get_storage_adapter()
    folder = _storage_folder(integration, batch)
    try:
        for index, (row, pdf) in enumerate(converted, start=1):
            path = posixpath.join(folder, "attachments", f"{index:02d}_{_safe_name(row.batch_source_filename)}.pdf")
            row.converted_pdf_path = await _slow(db, adapter.save, path, pdf)      # 5.1
            row.status = "CONVERTED"
            row.status_reason = "Converted to PDF and stored"
        db.commit()
        _log_event(db, batch, "ATTACHMENTS_CONVERTED", details={"count": len(converted)})

        email_pdf = await _slow(db, build_email_pdf, EmailMetadataForTrailer(        # 5.2
            from_email=f"{ctx.sender_name} <{ctx.sender_email}>" if ctx.sender_name else ctx.sender_email,
            to_email=ctx.recipient_email,
            subject=ctx.subject,
            body=ctx.body_text,
            received_datetime=ctx.received_at.strftime("%Y-%m-%d %H:%M %Z").strip(),
            attachments=[row.batch_source_filename for row, _ in converted],
            batch_no=batch.batch_no,
            summary=batch.ai_summary or "",
        ))
        batch.email_pdf_path = await _slow(db, adapter.save, posixpath.join(folder, "email_content.pdf"), email_pdf)
        db.commit()
        _log_event(db, batch, "EMAIL_PDF_CREATED")

        merged = await _slow(db, merge_pdfs, [pdf for _, pdf in converted] + [email_pdf])  # 5.3
        batch.merged_pdf_path = await _slow(db,                                            # 5.4
            adapter.save, posixpath.join(folder, f"{batch.batch_no}_merged.pdf"), merged,
        )
        for row, _pdf in converted:
            row.status = "MERGED"
            row.status_reason = "Converted, stored and merged"
        db.commit()
        _log_event(db, batch, "MERGED_PDF_STORED", details={"pages_from": len(converted) + 1})
    except Exception as exc:
        raise _SystemError(f"Could not store the PDFs: {type(exc).__name__}: {exc}") from exc

    await _reply(db, service, ctx, integration, batch, "success", "SUCCESS_REPLY",
                 {"file_list_html": file_list_html([(row.batch_source_filename, None) for row, _ in converted])})
    return _finish(db, batch, SUCCESS, "PROCESSED",                                                # 5.5
                   f"{len(converted)} attachment(s) converted, merged and stored")


# ── Manual reprocessing ───────────────────────────────────────
async def reprocess_batch(batch_id: int) -> str:
    """Re-fetch a batch's source email from the provider and run the flow again."""
    db = SessionLocal()
    try:
        batch = db.query(EmailBatch).filter(EmailBatch.id == batch_id).first()
        if not batch or not batch.integration_id:
            return FAILED
        integration = db.query(EmailIntegration).filter(EmailIntegration.id == batch.integration_id).first()
        if not integration or not integration.is_active:
            _finish(db, batch, FAILED, "SYSTEM_ERROR", "Reprocess failed: mailbox is disconnected")
            return FAILED
        provider_message_id = batch.conversation_id
        provider = integration.provider
        recipient = integration.email_address
        integration_id = integration.id
    finally:
        db.close()

    try:
        if provider == "gmail":
            from app.services.gmail_client import build_gmail_service
            from app.services.gmail_sync import build_intake_context_from_gmail

            service = await asyncio.to_thread(build_gmail_service, integration_id)
            msg = await asyncio.to_thread(
                lambda: service.users().messages().get(userId="me", id=provider_message_id, format="full").execute()
            )
            ctx = build_intake_context_from_gmail(msg, recipient)
        elif provider == "outlook":
            from app.services.document_intake.provider_adapters import OutlookGraphAdapter

            db = SessionLocal()
            try:
                integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
                service = OutlookGraphAdapter(integration)
            finally:
                db.close()
            message = await asyncio.to_thread(service.get_message, provider_message_id)
            ctx = service.build_context(message)
        elif provider == "imap":
            from app.services.document_intake.provider_adapters import IMAPDocumentAdapter

            db = SessionLocal()
            try:
                integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
                service = IMAPDocumentAdapter(integration)
            finally:
                db.close()
            item = await asyncio.to_thread(service.fetch_item, provider_message_id)
            if not item:
                raise RuntimeError("The email is no longer in the mailbox Inbox")
            ctx = service.context_for(item)
        else:
            raise RuntimeError(f"Reprocessing is not supported for provider '{provider}'")
    except Exception as exc:
        logger.error(f"[intake] Reprocess fetch failed for batch {batch_id}: {exc}")
        db = SessionLocal()
        try:
            batch = db.query(EmailBatch).filter(EmailBatch.id == batch_id).first()
            if batch:
                _log_event(db, batch, "REPROCESS_FAILED", details={"error": str(exc)[:1000]})
                _finish(db, batch, FAILED, "SYSTEM_ERROR",
                        f"Reprocess failed: could not re-fetch the email ({type(exc).__name__})")
        finally:
            db.close()
        return FAILED

    return await process_document_intake_email(integration_id, service, ctx, reprocess_batch_id=batch_id)
