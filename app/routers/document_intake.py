"""
Processed emails — list, detail (rules timeline + attachments), PDF downloads,
manual reprocessing, and the auto-reply templates for each rule.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.document_intake import EmailBatch, EmailBatchAttachment, EmailBatchEvent, EmailTemplate
from app.models.email import EmailIntegration
from app.models.user import User
from app.routers.auth import get_current_user, require_admin
from app.services.document_intake.storage.factory import get_adapter_for_path
from app.services.document_intake.template_renderer import (
    DEFAULT_TEMPLATES, PLACEHOLDERS, TEMPLATE_LABELS, render_template,
)

router = APIRouter()


def _scoped_batch_query(db: Session, current_user: User):
    query = db.query(EmailBatch)
    if current_user.role != "admin":
        query = query.join(EmailIntegration, EmailBatch.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    return query


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _batch_summary(b: EmailBatch) -> dict:
    return {
        "id": b.id,
        "batch_no": b.batch_no,
        "sender_name": b.sender_name,
        "sender_email": b.sender_email,
        "recipient_email": b.recipient_email,
        "subject": b.subject,
        "status": b.status,
        "outcome": b.outcome,
        "status_reason": b.status_reason,
        "mailbox_type": b.mailbox_type,
        "attachment_count": b.attachment_count or 0,
        "sentiment": b.sentiment,
        "sentiment_score": float(b.sentiment_score) if b.sentiment_score is not None else None,
        "primary_emotion": b.primary_emotion,
        "email_category": b.email_category,
        "priority": b.priority,
        "ai_summary": b.ai_summary,
        "has_merged_pdf": bool(b.merged_pdf_path),
        "is_archived": bool(b.is_archived),
        "archived_at": _iso(b.archived_at),
        "received_datetime": _iso(b.received_datetime),
        "processed_at": _iso(b.processed_at),
    }


@router.get("/batches")
def list_batches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    sentiment: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None, max_length=200),
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = _scoped_batch_query(db, current_user).filter(EmailBatch.received_datetime >= since)
    if status:
        q = q.filter(EmailBatch.status == status)
    if outcome:
        q = q.filter(EmailBatch.outcome == outcome)
    if category:
        q = q.filter(EmailBatch.email_category == category)
    if sentiment:
        q = q.filter(EmailBatch.sentiment == sentiment)
    if priority:
        q = q.filter(EmailBatch.priority == priority)
    if search:
        needle = f"%{search.strip()}%"
        q = q.filter(or_(
            EmailBatch.batch_no.ilike(needle),
            EmailBatch.sender_email.ilike(needle),
            EmailBatch.subject.ilike(needle),
        ))

    total = q.count()
    items = (
        q.order_by(EmailBatch.received_datetime.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"total": total, "page": page, "page_size": page_size, "items": [_batch_summary(b) for b in items]}


@router.get("/activity")
def recent_activity(
    since: Optional[datetime] = Query(None, description="Only emails finished after this time (ISO 8601)"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Emails that finished processing recently, newest first — drives the notification pop-ups."""
    q = _scoped_batch_query(db, current_user).filter(EmailBatch.processed_at.isnot(None))
    if since is not None:
        q = q.filter(EmailBatch.processed_at > (since if since.tzinfo else since.replace(tzinfo=timezone.utc)))
    items = q.order_by(EmailBatch.processed_at.desc()).limit(limit).all()
    return {"server_time": datetime.now(timezone.utc).isoformat(), "items": [_batch_summary(b) for b in items]}


def _get_batch(db: Session, current_user: User, batch_no: str) -> EmailBatch:
    batch = _scoped_batch_query(db, current_user).filter(EmailBatch.batch_no == batch_no).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Email not found")
    return batch


@router.get("/batches/{batch_no}")
def get_batch_detail(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = _get_batch(db, current_user, batch_no)
    events = (
        db.query(EmailBatchEvent)
        .filter(EmailBatchEvent.parent_batch_id == batch.id)
        .order_by(EmailBatchEvent.created_at.asc(), EmailBatchEvent.id.asc())
        .all()
    )
    attachments = (
        db.query(EmailBatchAttachment)
        .filter(EmailBatchAttachment.parent_batch_id == batch.id)
        .order_by(EmailBatchAttachment.id.asc())
        .all()
    )
    return {
        **_batch_summary(batch),
        "message_id": batch.message_id,
        "body_text": batch.body_text,
        "ai_model_version": batch.ai_model_version,
        "has_email_pdf": bool(batch.email_pdf_path),
        "events": [
            {
                "event_type": e.event_type,
                "related_filename": e.related_filename,
                "reply_sent": bool(e.reply_sent),
                "details": e.details or {},
                "created_at": _iso(e.created_at),
            }
            for e in events
        ],
        "attachments": [
            {
                "id": a.id,
                "filename": a.batch_source_filename,
                "doc_type": a.doc_type,
                "file_size_bytes": a.file_size_bytes,
                "is_encrypted": bool(a.is_encrypted),
                "status": a.status,
                "status_reason": a.status_reason,
                "has_pdf": bool(a.converted_pdf_path),
            }
            for a in attachments
        ],
    }


async def _pdf_response(stored_path: str | None, filename: str, archived: bool = False) -> Response:
    if not stored_path:
        detail = "The PDFs of this email were deleted by the retention policy" if archived else "PDF not found"
        raise HTTPException(status_code=404, detail=detail)
    adapter = get_adapter_for_path(stored_path)
    try:
        data = await asyncio.to_thread(adapter.read, stored_path)
    except (OSError, ValueError) as exc:
        logger.warning(f"[emails] Stored PDF missing ({stored_path}): {exc}")
        raise HTTPException(status_code=404, detail="The PDF file is no longer available")
    except Exception as exc:
        logger.error(f"[emails] Failed to read PDF {stored_path}: {exc}")
        raise HTTPException(status_code=502, detail="Could not read the PDF from storage")
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename)[:120] or "document.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.get("/batches/{batch_no}/download")
async def download_merged_pdf(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = _get_batch(db, current_user, batch_no)
    return await _pdf_response(batch.merged_pdf_path, f"{batch_no}_merged.pdf", bool(batch.is_archived))


@router.get("/batches/{batch_no}/email-pdf")
async def download_email_pdf(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = _get_batch(db, current_user, batch_no)
    return await _pdf_response(batch.email_pdf_path, f"{batch_no}_email_content.pdf", bool(batch.is_archived))


@router.get("/batches/{batch_no}/attachments/{attachment_id}/pdf")
async def download_attachment_pdf(
    batch_no: str, attachment_id: int,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    batch = _get_batch(db, current_user, batch_no)
    row = db.query(EmailBatchAttachment).filter(
        EmailBatchAttachment.id == attachment_id, EmailBatchAttachment.parent_batch_id == batch.id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attachment not found")
    stem = row.batch_source_filename.rsplit(".", 1)[0]
    return await _pdf_response(row.converted_pdf_path, f"{stem}.pdf", bool(batch.is_archived))


class ReprocessResponse(BaseModel):
    message: str
    batch_no: str


@router.post("/batches/{batch_no}/reprocess", response_model=ReprocessResponse)
async def reprocess_batch(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Fetch the source email again and re-run the rules (for FAILED or REJECTED emails)."""
    batch = _get_batch(db, current_user, batch_no)
    if batch.status == "SUCCESS":
        raise HTTPException(status_code=400, detail="This email was already processed successfully")
    if batch.status in ("RECEIVED", "PROCESSING", "REPROCESSING"):
        raise HTTPException(status_code=409, detail="This email is already being processed")

    batch.status = "REPROCESSING"
    batch.status_reason = "Queued for reprocessing"
    db.commit()

    from app.jobs.queue import enqueue
    await enqueue("reprocess_batch", batch.id, job_id=f"reprocess:{batch.id}:{int(datetime.now(timezone.utc).timestamp())}")
    return ReprocessResponse(message="Email queued for reprocessing", batch_no=batch_no)


# ── Auto-reply templates (one per rule; global default + optional per-mailbox override) ──
class TemplateUpdate(BaseModel):
    subject_template: Optional[str] = Field(None, min_length=1, max_length=500)
    html_body_template: Optional[str] = Field(None, min_length=1, max_length=50_000)
    signature_html: Optional[str] = Field(None, max_length=10_000)

    @field_validator("subject_template")
    @classmethod
    def single_line_subject(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and ("\r" in value or "\n" in value):
            raise ValueError("Subject must be a single line")
        return value


class TemplateTestRequest(BaseModel):
    integration_id: int
    to: Optional[str] = Field(None, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _template_row(db: Session, key: str, integration_id: int | None) -> EmailTemplate | None:
    scope = (EmailTemplate.integration_id == integration_id) if integration_id is not None else EmailTemplate.integration_id.is_(None)
    return db.query(EmailTemplate).filter(scope, EmailTemplate.template_key == key, EmailTemplate.locale == "en").first()


def _template_out(key: str, row: EmailTemplate | None, fallback: EmailTemplate | None = None, integration_id: int | None = None) -> dict:
    """``row`` is the mailbox override (or the global row when integration_id is None)."""
    subject, body = DEFAULT_TEMPLATES[key]
    effective = row or fallback
    return {
        "template_key": key,
        "label": TEMPLATE_LABELS[key],
        "placeholders": PLACEHOLDERS[key],
        "subject_template": effective.subject_template if effective else subject,
        "html_body_template": effective.html_body_template if effective else body,
        "signature_html": (effective.signature_html if effective else None) or "",
        "is_default": effective is None or (effective.subject_template, effective.html_body_template) == (subject, body),
        "integration_id": integration_id,
        "is_override": integration_id is not None and row is not None,
    }


def _check_mailbox(db: Session, integration_id: int | None) -> None:
    if integration_id is not None and not db.query(EmailIntegration.id).filter(EmailIntegration.id == integration_id).first():
        raise HTTPException(status_code=404, detail="Mailbox not found")


def _check_key(template_key: str) -> None:
    if template_key not in DEFAULT_TEMPLATES:
        raise HTTPException(status_code=404, detail="Unknown template")


_SAMPLE_CONTEXT = {
    "subject": "Claim documents",
    "batch_no": "CLM-PROD-20261001-000001",
    "domain": "example.org",
    "allowed_extensions": ".pdf, .doc, .docx, .tiff, .tif",
    "max_file_size_mb": 25,
    "file_list_html": "<ul><li><strong>invoice.pdf</strong></li><li><strong>scan.tiff</strong></li></ul>",
}


@router.get("/templates")
def list_templates(
    integration_id: Optional[int] = Query(None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Global templates, or the effective templates of one mailbox (override if any, else global)."""
    _check_mailbox(db, integration_id)
    return [
        _template_out(key, _template_row(db, key, integration_id),
                      _template_row(db, key, None) if integration_id is not None else None, integration_id)
        for key in DEFAULT_TEMPLATES
    ]


@router.put("/templates/{template_key}")
def update_template(
    template_key: str, payload: TemplateUpdate,
    integration_id: Optional[int] = Query(None),
    db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    """Save the global text, or (with integration_id) a mailbox-specific override."""
    _check_key(template_key)
    _check_mailbox(db, integration_id)
    row = _template_row(db, template_key, integration_id)
    if row is None:
        base = _template_row(db, template_key, None) if integration_id is not None else None
        subject, body = (base.subject_template, base.html_body_template) if base else DEFAULT_TEMPLATES[template_key]
        row = EmailTemplate(integration_id=integration_id, template_key=template_key, locale="en",
                            subject_template=subject, html_body_template=body,
                            signature_html=base.signature_html if base else None, is_active=True)
        db.add(row)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        if field_name == "signature_html":
            value = value or None
        setattr(row, field_name, value)
    row.is_active = True
    db.commit()
    db.refresh(row)
    fallback = _template_row(db, template_key, None) if integration_id is not None else None
    return _template_out(template_key, row, fallback, integration_id)


@router.post("/templates/{template_key}/reset")
def reset_template(
    template_key: str,
    integration_id: Optional[int] = Query(None),
    db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    """Global: back to the built-in text. Mailbox: remove the override (use the global text again)."""
    _check_key(template_key)
    _check_mailbox(db, integration_id)
    row = _template_row(db, template_key, integration_id)
    if integration_id is not None:
        if row is not None:
            db.delete(row)
            db.commit()
        return _template_out(template_key, None, _template_row(db, template_key, None), integration_id)
    if row is not None:
        row.subject_template, row.html_body_template = DEFAULT_TEMPLATES[template_key]
        row.signature_html = None
        row.is_active = True
        db.commit()
        db.refresh(row)
    return _template_out(template_key, row)


@router.get("/templates/{template_key}/preview")
def preview_template(
    template_key: str,
    integration_id: Optional[int] = Query(None),
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    _check_key(template_key)
    rendered = render_template(db, template_key, dict(_SAMPLE_CONTEXT), integration_id=integration_id)
    return {"subject": rendered.subject, "html_body": rendered.html_body}


@router.post("/templates/{template_key}/test")
async def send_test_template(
    template_key: str, payload: TemplateTestRequest,
    db: Session = Depends(get_db), admin: User = Depends(require_admin),
):
    """Send the reply (sample data) from a connected mailbox — to the mailbox itself unless ``to`` is given."""
    from app.services.mail_sender import MailSendError, send_new_message

    _check_key(template_key)
    mailbox = db.query(EmailIntegration).filter(EmailIntegration.id == payload.integration_id).first()
    if not mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    recipient = payload.to or mailbox.email_address
    rendered = render_template(db, template_key, dict(_SAMPLE_CONTEXT), integration_id=mailbox.id)
    try:
        await asyncio.to_thread(send_new_message, mailbox.id, recipient, f"[TEST] {rendered.subject}", rendered.html_body)
    except MailSendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    logger.info(f"[templates] Test '{template_key}' sent from {mailbox.email_address} to {recipient} by {admin.username}")
    return {"message": f"Test email sent from {mailbox.email_address} to {recipient}"}
