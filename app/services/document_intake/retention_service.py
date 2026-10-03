"""
Retention: free storage by deleting the stored PDFs of old emails.

Once an email finished more than ``retention_days`` ago (per mailbox, default
DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS), its merged PDF, email-content PDF and
per-attachment PDFs are deleted and the email is marked archived. The record,
AI analysis, attachment statuses and timeline stay in the database.
Runs daily from the background scheduler.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models.document_intake import EmailBatch, EmailBatchAttachment, EmailBatchEvent
from app.models.email import EmailIntegration
from app.services.document_intake.storage.factory import get_adapter_for_path

FINAL_STATUSES = ("SUCCESS", "REJECTED", "FAILED", "IGNORED")


def _delete(path: str | None) -> None:
    if path:
        get_adapter_for_path(path).delete(path)


def archive_batch(db, batch: EmailBatch, now: datetime, retention_days: int) -> bool:
    """Delete one email's stored PDFs and mark it archived. False if a file could not be deleted."""
    attachments = db.query(EmailBatchAttachment).filter(EmailBatchAttachment.parent_batch_id == batch.id).all()
    try:
        _delete(batch.merged_pdf_path)
        _delete(batch.email_pdf_path)
        for row in attachments:
            _delete(row.converted_pdf_path)
    except Exception as exc:
        # Leave it unarchived; the next daily run retries.
        logger.warning(f"[retention] Could not delete PDFs of {batch.batch_no}: {exc}")
        db.rollback()
        return False

    removed = sum(1 for p in [batch.merged_pdf_path, batch.email_pdf_path, *(r.converted_pdf_path for r in attachments)] if p)
    batch.merged_pdf_path = None
    batch.email_pdf_path = None
    for row in attachments:
        row.converted_pdf_path = None
    batch.is_archived = True
    batch.archived_at = now
    db.add(EmailBatchEvent(
        parent_batch_id=batch.id, batch_no=batch.batch_no, event_type="ARCHIVED",
        details={"retention_days": retention_days, "files_deleted": removed},
    ))
    db.commit()
    return True


def archive_old_batches() -> int:
    """Archive every finished email older than its mailbox's retention period. Returns how many."""
    db = SessionLocal()
    archived = 0
    try:
        now = datetime.now(timezone.utc)
        scopes = [
            (EmailBatch.integration_id == mailbox.id, mailbox.retention_days or settings.DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS)
            for mailbox in db.query(EmailIntegration).all()
        ]
        # Emails whose mailbox was deleted use the global default.
        scopes.append((EmailBatch.integration_id.is_(None), settings.DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS))

        for scope, days in scopes:
            cutoff = now - timedelta(days=days)
            batches = db.query(EmailBatch).filter(
                scope,
                EmailBatch.is_archived.isnot(True),
                EmailBatch.status.in_(FINAL_STATUSES),
                EmailBatch.processed_at.isnot(None),
                EmailBatch.processed_at < cutoff,
            ).all()
            for batch in batches:
                if archive_batch(db, batch, now, days):
                    archived += 1
        if archived:
            logger.info(f"[retention] Archived {archived} email(s) and deleted their stored PDFs")
        return archived
    finally:
        db.close()
