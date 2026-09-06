"""
Document Intake Pipeline orchestrator (§5, §6).
Ties together validation, attachment policy, encryption checks, conversion,
merge, AI analysis, storage, mailbox move, and client callback notification
into the single end-to-end flow described in DOCUMENT_INTAKE_BATCH_PROCESSING_PLAN.md.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone
from dataclasses import dataclass

from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.config import settings
from app.models.email import EmailIntegration
from app.models.document_intake import EmailBatch, EmailBatchEvent, EmailBatchAttachment

from app.services.document_intake.batch_id_generator import generate_batch_no
from app.services.document_intake.domain_validator import validate_domain, is_system_sender
from app.services.document_intake.autoreply_detector import is_autoreply
from app.services.document_intake.attachment_extractor import (
    extract_attachments_from_gmail_payload, has_attachments,
)
from app.services.document_intake.file_policy_validator import validate_file_policy
from app.services.document_intake.encryption_checker import check_encryption
from app.services.document_intake.conversion.pdf_passthrough import convert_pdf_passthrough
from app.services.document_intake.conversion.doc_to_pdf import convert_doc_to_pdf, DocConversionError
from app.services.document_intake.conversion.tiff_to_pdf import convert_tiff_to_pdf
from app.services.document_intake.pdf_merger import merge_pdfs_with_trailer, EmailMetadataForTrailer
from app.services.document_intake.storage.factory import get_storage_adapter
from app.services.document_intake.mailbox_folder_service import move_to_success, move_to_failed
from app.services.document_intake.client_callback_notifier import send_callback
from app.services.document_intake.sensitive_data_detector import detect_sensitivity, extract_attachment_text
from app.services.document_intake.template_renderer import render_template, seed_default_templates

from app.services.sentiment_analyzer import analyze_sentiment
from app.services.classifier import classify_email
from app.services.emotion_detector import detect_emotions
from app.services.ai_client import get_model, ai_available


@dataclass
class IntakeEmailContext:
    """Pre-parsed email fields (avoids re-parsing Gmail payload/headers already done by the caller)."""
    gmail_message_id: str
    stored_message_id: str
    thread_id: str | None
    headers: dict[str, str]
    sender_name: str
    sender_email: str
    recipient_email: str
    subject: str
    received_at: datetime
    payload: dict


def _log_event(
    db: Session,
    batch: EmailBatch,
    event_type: str,
    related_filename: str | None = None,
    details: dict | None = None,
    reply_sent: bool = False,
) -> None:
    db.add(
        EmailBatchEvent(
            parent_batch_id=batch.id,
            batch_no=batch.batch_no,
            event_type=event_type,
            related_filename=related_filename,
            reply_sent=reply_sent,
            details=details or {},
        )
    )
    db.commit()


def _reject_batch(db: Session, batch: EmailBatch, reason: str) -> None:
    batch.status = "REJECTED"
    batch.status_reason = reason
    batch.processed_at = datetime.now(timezone.utc)
    db.commit()


def _send_auto_reply(
    db: Session,
    service,
    ctx: IntakeEmailContext,
    integration: EmailIntegration,
    template_key: str,
    template_context: dict,
) -> bool:
    """Render the branded HTML template (open question #1) and send via Gmail API. Returns True if sent."""
    if is_system_sender(ctx.sender_email):
        return False
    try:
        rendered = render_template(
            db, template_key,
            context={"subject": ctx.subject, **template_context},
            integration_id=integration.id,
        )

        if hasattr(service, "send_reply"):
            return bool(service.send_reply(ctx, rendered.subject, rendered.html_body))

        import base64
        from email.mime.text import MIMEText
        msg = MIMEText(rendered.html_body, "html")
        msg["To"] = ctx.sender_email
        msg["From"] = ctx.recipient_email
        msg["Subject"] = rendered.subject
        if ctx.thread_id:
            msg["In-Reply-To"] = ctx.headers.get("Message-ID", "")
            msg["References"] = ctx.headers.get("Message-ID", "")

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        send_body: dict = {"raw": raw}
        if ctx.thread_id:
            send_body["threadId"] = ctx.thread_id

        service.users().messages().send(userId="me", body=send_body).execute()
        return True
    except Exception as exc:
        logger.warning(f"[document_intake.pipeline] Auto-reply failed: {exc}")
        return False


async def _finalize_and_callback(
    db: Session,
    batch: EmailBatch,
    integration: EmailIntegration,
    service,
    ctx: IntakeEmailContext,
) -> None:
    """Common terminal-state handling: mailbox move + client callback (§5 steps 10/11/12)."""
    # Specialized rejection branches may already have sent a reply. Only send
    # the configurable terminal notification when no earlier reply was sent.
    prior_reply = (
        db.query(EmailBatchEvent)
        .filter(EmailBatchEvent.parent_batch_id == batch.id, EmailBatchEvent.reply_sent == True)
        .first()
    )
    reply_enabled = (
        integration.success_auto_reply_enabled
        if batch.status == "SUCCESS"
        else integration.failure_auto_reply_enabled
    )
    if reply_enabled and not prior_reply and not is_autoreply(ctx.headers):
        template_key = "success" if batch.status == "SUCCESS" else "failure"
        replied = _send_auto_reply(
            db,
            service,
            ctx,
            integration,
            template_key,
            {
                "batch_no": batch.batch_no,
                "reason": batch.status_reason or "The document could not be processed.",
            },
        )
        _log_event(db, batch, "SUCCESS_AUTO_REPLY" if batch.status == "SUCCESS" else "FAILURE_AUTO_REPLY", reply_sent=replied)

    gmail_message_id = None
    # batch.message_id may be the stable RFC Message-ID; the Gmail API message id is
    # tracked separately by the caller and passed through via batch.conversation_id's
    # sibling context when needed. For label moves we re-resolve via the Gmail id if present.
    try:
        if batch.status == "SUCCESS":
            if service and integration.success_folder_label:
                if hasattr(service, "move_to_success"):
                    service.move_to_success(batch.conversation_id or "", integration.success_folder_label)
                else:
                    move_to_success(service, batch.conversation_id or "", integration.success_folder_label)
        else:
            if service and integration.failed_folder_label:
                if hasattr(service, "move_to_failed"):
                    service.move_to_failed(batch.conversation_id or "", integration.failed_folder_label)
                else:
                    move_to_failed(service, batch.conversation_id or "", integration.failed_folder_label)
    except Exception as exc:
        logger.warning(f"[document_intake.pipeline] Mailbox move failed for {batch.batch_no}: {exc}")

    if integration.callback_enabled and integration.callback_webhook_url:
        try:
            delivered = await send_callback(
                db, batch, integration.callback_webhook_url, integration.callback_auth_header,
            )
            _log_event(db, batch, "CALLBACK_SENT" if delivered else "CALLBACK_FAILED")
        except Exception as exc:
            logger.error(f"[document_intake.pipeline] Callback dispatch error for {batch.batch_no}: {exc}")
            _log_event(db, batch, "CALLBACK_FAILED", details={"error": str(exc)})


async def process_document_intake_email(
    integration_id: int,
    service,
    ctx: IntakeEmailContext,
) -> str:
    """
    Full end-to-end document-intake pipeline for a single inbound email (§5).
    Returns the final batch status: SUCCESS | REJECTED | FAILED.
    """
    db = SessionLocal()
    try:
        integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        if not integration:
            logger.error(f"[document_intake.pipeline] Integration {integration_id} not found")
            return "FAILED"

        existing_batch = (
            db.query(EmailBatch)
            .filter(
                EmailBatch.integration_id == integration_id,
                EmailBatch.message_id == ctx.stored_message_id,
            )
            .first()
        )
        if existing_batch:
            logger.info(
                f"[document_intake.pipeline] Skipping duplicate message "
                f"{ctx.stored_message_id} for integration {integration_id}"
            )
            return existing_batch.status or "RECEIVED"

        seed_default_templates(db)

        # ── Step 1: Parent entry + Batch ID ────────────────────
        batch_no = generate_batch_no(db, integration.batch_prefix, integration.mailbox_type)
        batch = EmailBatch(
            batch_no=batch_no,
            message_id=ctx.stored_message_id,
            conversation_id=ctx.gmail_message_id,
            integration_id=integration.id,
            mailbox_type=integration.mailbox_type,
            sender_email=ctx.sender_email,
            recipient_email=ctx.recipient_email,
            subject=ctx.subject,
            received_datetime=ctx.received_at,
            status="RECEIVED",
        )
        db.add(batch)
        db.commit()
        db.refresh(batch)

        # ── Step 2: Domain validation ───────────────────────────
        domain_check = validate_domain(db, ctx.sender_email)
        if not domain_check.is_allowed:
            replied = False
            if integration.auto_reply_invalid_domain:
                replied = _send_auto_reply(
                    db, service, ctx, integration, "domain_rejected", {"domain": domain_check.domain},
                )
            _log_event(db, batch, "DOMAIN_REJECTED", details={"domain": domain_check.domain}, reply_sent=replied)
            _reject_batch(db, batch, domain_check.reason)
            await _finalize_and_callback(db, batch, integration, service, ctx)
            return "REJECTED"

        # ── Step 3: Auto-reply/OOO detection ────────────────────
        sender_is_autoreply = is_autoreply(ctx.headers)
        if sender_is_autoreply:
            _log_event(db, batch, "AUTO_REPLY_SKIPPED")

        # ── Step 4: No attachment check ─────────────────────────
        attachment_present = service.has_attachments(ctx) if hasattr(service, "has_attachments") else has_attachments(ctx.payload)
        if not attachment_present:
            replied = False
            if integration.auto_reply_no_attachment and not sender_is_autoreply:
                replied = _send_auto_reply(db, service, ctx, integration, "no_attachment", {})
            _log_event(db, batch, "NO_ATTACHMENT", reply_sent=replied)
            _reject_batch(db, batch, "No attachment found to process")
            await _finalize_and_callback(db, batch, integration, service, ctx)
            return "REJECTED"

        # ── Step 5: Extract attachments + create tracking rows ──
        if hasattr(service, "extract_attachments"):
            extracted = service.extract_attachments(ctx)
        else:
            extracted = extract_attachments_from_gmail_payload(service, ctx.gmail_message_id, ctx.payload)
        batch.attachment_count = len(extracted)
        db.commit()

        attachment_rows: list[EmailBatchAttachment] = []
        for att in extracted:
            row = EmailBatchAttachment(
                parent_batch_id=batch.id,
                batch_no=batch.batch_no,
                batch_source_filename=att.filename,
                doc_type=att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else "",
                file_size_bytes=att.size_bytes,
                received_date=ctx.received_at,
                status="PENDING",
            )
            db.add(row)
            attachment_rows.append(row)
        db.commit()
        for row in attachment_rows:
            db.refresh(row)

        # ── Step 6: Extension/size policy ───────────────────────
        invalid_files: list[str] = []
        for att, row in zip(extracted, attachment_rows):
            policy = validate_file_policy(
                att.filename, att.size_bytes,
                integration.allowed_extensions, integration.max_file_size_mb,
            )
            if not policy.is_allowed:
                row.status = "SKIPPED_INVALID_TYPE"
                row.status_reason = policy.reason
                invalid_files.append(att.filename)
        db.commit()

        if invalid_files:
            _log_event(
                db, batch, "INVALID_FILE_TYPE",
                details={"files": invalid_files},
            )
            replied = _send_auto_reply(
                db, service, ctx, integration, "invalid_file_type",
                {"files": ", ".join(invalid_files), "allowed_extensions": integration.allowed_extensions},
            )
            _log_event(db, batch, "INVALID_FILE_TYPE", reply_sent=replied)
            _reject_batch(db, batch, "Attachment file type/size not supported")
            await _finalize_and_callback(db, batch, integration, service, ctx)
            return "REJECTED"

        # ── Step 7: Encryption/password detection ───────────────
        encrypted_files: list[str] = []
        valid_pairs: list[tuple] = []  # (attachment, row, raw_bytes)
        for att, row in zip(extracted, attachment_rows):
            enc_check = check_encryption(att.filename, att.data)
            row.is_encrypted = enc_check.is_encrypted
            if enc_check.is_encrypted:
                row.status = "SKIPPED_ENCRYPTED"
                row.status_reason = enc_check.reason
                encrypted_files.append(att.filename)
            else:
                valid_pairs.append((att, row))
        db.commit()

        if encrypted_files:
            replied = _send_auto_reply(
                db, service, ctx, integration, "encrypted_file", {"files": ", ".join(encrypted_files)},
            )
            _log_event(db, batch, "ENCRYPTED_FILE", details={"files": encrypted_files}, reply_sent=replied)
            _reject_batch(db, batch, f"Password-protected/encrypted file(s) found: {', '.join(encrypted_files)}")
            await _finalize_and_callback(db, batch, integration, service, ctx)
            return "REJECTED"

        # ── Step 8: Convert + merge + trailer page ──────────────
        converted_pdfs: list[bytes] = []
        conversion_errors: list[str] = []
        for att, row in valid_pairs:
            try:
                ext = row.doc_type
                if ext == "pdf":
                    pdf_bytes = convert_pdf_passthrough(att.data)
                elif ext in ("doc", "docx"):
                    pdf_bytes = convert_doc_to_pdf(att.data, att.filename)
                elif ext in ("tiff", "tif"):
                    pdf_bytes = convert_tiff_to_pdf(att.data)
                else:
                    raise ValueError(f"Unsupported doc_type: {ext}")

                row.status = "CONVERTED"
                converted_pdfs.append(pdf_bytes)
            except (DocConversionError, Exception) as exc:
                row.status = "FAILED"
                row.status_reason = str(exc)[:500]
                conversion_errors.append(f"{att.filename}: {exc}")
        db.commit()

        if not converted_pdfs:
            _log_event(db, batch, "CONVERSION_ERROR", details={"errors": conversion_errors})
            _reject_batch(db, batch, f"Document conversion failed: {'; '.join(conversion_errors)[:500]}")
            batch.status = "FAILED"
            db.commit()
            await _finalize_and_callback(db, batch, integration, service, ctx)
            return "FAILED"

        body_text_for_meta = ctx.headers.get("_body_plain", "")
        try:
            merged_pdf = merge_pdfs_with_trailer(
                converted_pdfs,
                EmailMetadataForTrailer(
                    from_email=ctx.sender_email,
                    to_email=ctx.recipient_email,
                    subject=ctx.subject,
                    body=body_text_for_meta,
                    received_datetime=ctx.received_at.isoformat(),
                ),
            )
            for _, row in valid_pairs:
                if row.status == "CONVERTED":
                    row.status = "MERGED"
            db.commit()
            _log_event(db, batch, "MERGE_SUCCESS")
        except Exception as exc:
            _log_event(db, batch, "CONVERSION_ERROR", details={"error": str(exc)})
            batch.status = "FAILED"
            batch.status_reason = f"PDF merge failed: {exc}"
            batch.processed_at = datetime.now(timezone.utc)
            db.commit()
            await _finalize_and_callback(db, batch, integration, service, ctx)
            return "FAILED"

        # ── Step (§1.2): AI analysis — sentiment/category/emotion + sensitivity ──
        try:
            sentiment = analyze_sentiment(body_text_for_meta)
            emotions = detect_emotions(body_text_for_meta)
            classification = await classify_email(body_text_for_meta)
            attachment_text = "\n".join(
                extract_attachment_text(att.filename, att.data)
                for att, _row in valid_pairs
            )
            sensitivity = await detect_sensitivity(
                f"{body_text_for_meta}\n\n{attachment_text}".strip()
            )

            batch.sentiment = sentiment.label
            batch.sentiment_score = sentiment.score
            batch.primary_emotion = emotions.primary_emotion
            batch.email_category = classification.category
            batch.sensitivity_level = sensitivity.sensitivity_level
            batch.contains_pii = sensitivity.contains_pii
            batch.pii_types_json = sensitivity.pii_types
            batch.ai_model_version = get_model() if ai_available() else "vader-rules-engine"
            db.commit()

            if sensitivity.contains_pii or sensitivity.sensitivity_level in ("confidential", "restricted"):
                _log_event(
                    db, batch, "SENSITIVE_DATA_DETECTED",
                    details={"sensitivity_level": sensitivity.sensitivity_level, "pii_types": sensitivity.pii_types},
                )
        except Exception as exc:
            logger.warning(f"[document_intake.pipeline] AI analysis failed for {batch.batch_no}: {exc}")

        # ── Step 9: Storage ──────────────────────────────────────
        try:
            adapter = get_storage_adapter(integration.storage_provider)
            relative_path = os.path.join(
                integration.mailbox_type or "PROD",
                ctx.received_at.strftime("%Y"), ctx.received_at.strftime("%m"),
                f"{batch.batch_no}.pdf",
            )
            saved_path = adapter.save(relative_path, merged_pdf)
            batch.merged_pdf_path = saved_path
            _log_event(db, batch, "STORAGE_SUCCESS", details={"path": saved_path})
        except Exception as exc:
            _log_event(db, batch, "CONVERSION_ERROR", details={"error": f"Storage failed: {exc}"})
            batch.status = "FAILED"
            batch.status_reason = f"Storage failed: {exc}"
            batch.processed_at = datetime.now(timezone.utc)
            db.commit()
            await _finalize_and_callback(db, batch, integration, service, ctx)
            return "FAILED"

        # ── Step 10: Success finalization ───────────────────────
        batch.status = "SUCCESS"
        batch.status_reason = "Merged PDF generated and stored successfully"
        batch.processed_at = datetime.now(timezone.utc)
        db.commit()
        _log_event(db, batch, "EMAIL_MOVED")

        await _finalize_and_callback(db, batch, integration, service, ctx)
        return "SUCCESS"

    finally:
        db.close()
