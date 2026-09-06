"""
Document Intake router (§6) — batch list/detail/download/reprocess/resend-callback
and admin settings extension for document-intake integration fields.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.document_intake import (
    EmailBatch, EmailBatchEvent, EmailBatchAttachment, EmailBatchCallback, EmailTemplate,
)
from app.models.email import EmailIntegration
from app.services.document_intake.client_callback_notifier import send_callback
from app.services.document_intake.template_renderer import seed_default_templates
from app.routers.auth import get_current_user, require_admin
from app.models.user import User

router = APIRouter()


def _scoped_batch_query(db: Session, current_user: User):
    query = db.query(EmailBatch)
    if current_user.role != "admin":
        query = query.join(EmailIntegration, EmailBatch.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    return query


@router.get("/batches")
def list_batches(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: Optional[str] = Query(None),
    mailbox_type: Optional[str] = Query(None),
    archived: Optional[bool] = Query(False),
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = _scoped_batch_query(db, current_user).filter(EmailBatch.received_datetime >= since)

    if status:
        q = q.filter(EmailBatch.status == status)
    if mailbox_type:
        q = q.filter(EmailBatch.mailbox_type == mailbox_type)
    if archived is not None:
        q = q.filter(EmailBatch.is_archived == archived)

    total = q.count()
    items = (
        q.order_by(EmailBatch.received_datetime.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": b.id,
                "batch_no": b.batch_no,
                "sender_email": b.sender_email,
                "subject": b.subject,
                "status": b.status,
                "status_reason": b.status_reason,
                "mailbox_type": b.mailbox_type,
                "attachment_count": b.attachment_count,
                "sentiment": b.sentiment,
                "email_category": b.email_category,
                "sensitivity_level": b.sensitivity_level,
                "contains_pii": b.contains_pii,
                "received_datetime": b.received_datetime.isoformat() if b.received_datetime else None,
                "processed_at": b.processed_at.isoformat() if b.processed_at else None,
                "is_archived": b.is_archived,
            }
            for b in items
        ],
    }


@router.get("/batches/{batch_no}")
def get_batch_detail(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = _scoped_batch_query(db, current_user).filter(EmailBatch.batch_no == batch_no).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    events = (
        db.query(EmailBatchEvent)
        .filter(EmailBatchEvent.parent_batch_id == batch.id)
        .order_by(EmailBatchEvent.created_at.asc())
        .all()
    )
    attachments = (
        db.query(EmailBatchAttachment)
        .filter(EmailBatchAttachment.parent_batch_id == batch.id)
        .all()
    )
    callbacks = (
        db.query(EmailBatchCallback)
        .filter(EmailBatchCallback.parent_batch_id == batch.id)
        .order_by(EmailBatchCallback.created_at.asc())
        .all()
    )

    return {
        "batch_no": batch.batch_no,
        "message_id": batch.message_id,
        "sender_email": batch.sender_email,
        "recipient_email": batch.recipient_email,
        "subject": batch.subject,
        "status": batch.status,
        "status_reason": batch.status_reason,
        "mailbox_type": batch.mailbox_type,
        "attachment_count": batch.attachment_count,
        "merged_pdf_path": batch.merged_pdf_path,
        "sentiment": batch.sentiment,
        "sentiment_score": float(batch.sentiment_score) if batch.sentiment_score is not None else None,
        "primary_emotion": batch.primary_emotion,
        "email_category": batch.email_category,
        "sensitivity_level": batch.sensitivity_level,
        "contains_pii": batch.contains_pii,
        "pii_types": batch.pii_types_json or [],
        "ai_model_version": batch.ai_model_version,
        "received_datetime": batch.received_datetime.isoformat() if batch.received_datetime else None,
        "processed_at": batch.processed_at.isoformat() if batch.processed_at else None,
        "events": [
            {
                "event_type": e.event_type,
                "related_filename": e.related_filename,
                "reply_sent": e.reply_sent,
                "details": e.details,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ],
        "attachments": [
            {
                "filename": a.batch_source_filename,
                "doc_type": a.doc_type,
                "file_size_bytes": a.file_size_bytes,
                "is_encrypted": a.is_encrypted,
                "status": a.status,
                "status_reason": a.status_reason,
            }
            for a in attachments
        ],
        "callbacks": [
            {
                "attempt_no": c.attempt_no,
                "delivered": c.delivered,
                "http_status_code": c.http_status_code,
                "error_detail": c.error_detail,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in callbacks
        ],
    }


@router.get("/batches/{batch_no}/download")
def download_merged_pdf(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = _scoped_batch_query(db, current_user).filter(EmailBatch.batch_no == batch_no).first()
    if not batch or not batch.merged_pdf_path:
        raise HTTPException(status_code=404, detail="Merged PDF not found for this batch")
    return FileResponse(batch.merged_pdf_path, media_type="application/pdf", filename=f"{batch_no}.pdf")


@router.post("/batches/{batch_no}/resend-callback")
async def resend_callback(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    batch = _scoped_batch_query(db, current_user).filter(EmailBatch.batch_no == batch_no).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    integration = db.query(EmailIntegration).filter(EmailIntegration.id == batch.integration_id).first()
    if not integration or not integration.callback_webhook_url:
        raise HTTPException(status_code=400, detail="No callback webhook configured for this integration")

    delivered = await send_callback(db, batch, integration.callback_webhook_url, integration.callback_auth_header)
    return {"delivered": delivered}


class ReprocessResponse(BaseModel):
    message: str
    batch_no: str


@router.post("/batches/{batch_no}/reprocess", response_model=ReprocessResponse)
def reprocess_batch(batch_no: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Reset a FAILED/REJECTED batch back to RECEIVED so the next poller cycle
    (or a manual trigger) can re-attempt it. Actual re-fetch of the source
    email bytes happens on the next sync cycle since Gmail message content
    is not duplicated into local storage for rejected/failed batches.
    """
    batch = _scoped_batch_query(db, current_user).filter(EmailBatch.batch_no == batch_no).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status == "SUCCESS":
        raise HTTPException(status_code=400, detail="Cannot reprocess a successfully completed batch")

    batch.status = "RECEIVED"
    batch.status_reason = "Manually queued for reprocessing"
    db.commit()
    return ReprocessResponse(message="Batch queued for reprocessing", batch_no=batch_no)


# ── Branded/localized auto-reply templates (open question #1) ─────────────

class TemplateCreate(BaseModel):
    integration_id: Optional[int] = None   # None = global default
    template_key: str                       # domain_rejected | no_attachment | invalid_file_type | encrypted_file
    locale: str = "en"
    subject_template: str
    html_body_template: str
    is_active: bool = True


class TemplateUpdate(BaseModel):
    subject_template: Optional[str] = None
    html_body_template: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/templates")
def list_templates(
    db: Session = Depends(get_db),
    integration_id: Optional[int] = Query(None),
    admin: User = Depends(require_admin),
):
    seed_default_templates(db)
    q = db.query(EmailTemplate)
    if integration_id is not None:
        q = q.filter(EmailTemplate.integration_id == integration_id)
    templates = q.order_by(EmailTemplate.template_key).all()
    return [
        {
            "id": t.id,
            "integration_id": t.integration_id,
            "template_key": t.template_key,
            "locale": t.locale,
            "subject_template": t.subject_template,
            "html_body_template": t.html_body_template,
            "is_active": t.is_active,
        }
        for t in templates
    ]


@router.post("/templates", status_code=201)
def create_template(payload: TemplateCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    template = EmailTemplate(**payload.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    return {"id": template.id, "message": "Template created"}


@router.patch("/templates/{template_id}")
def update_template(template_id: int, payload: TemplateUpdate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, field_name, value)

    db.commit()
    return {"message": "Template updated"}


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()
    return {"message": "Template deleted"}
