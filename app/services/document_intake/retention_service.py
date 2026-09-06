"""
Retention & archival service (open question #5) — monthly/periodic archival
of processed document-intake batches, per-integration configurable via
`email_integrations.retention_days` (Admin Settings).
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone

from loguru import logger

from app.config import settings
from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.models.document_intake import EmailBatch
from app.services.document_intake.storage.factory import get_storage_adapter


def archive_old_batches() -> int:
    """
    Archive terminal-state batches older than each integration's retention_days.
    Archiving deletes the merged PDF from storage (space reclamation) and flags
    the DB row as archived — audit trail (batch/events/attachments) is preserved.
    """
    db = SessionLocal()
    archived_count = 0
    try:
        integrations = db.query(EmailIntegration).all()
        for integration in integrations:
            retention_days = integration.retention_days or settings.DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

            candidates = (
                db.query(EmailBatch)
                .filter(
                    EmailBatch.integration_id == integration.id,
                    EmailBatch.is_archived == False,
                    EmailBatch.status.in_(("SUCCESS", "REJECTED", "FAILED")),
                    EmailBatch.processed_at.isnot(None),
                    EmailBatch.processed_at < cutoff,
                )
                .all()
            )

            if not candidates:
                continue

            adapter = get_storage_adapter(integration.storage_provider)
            for batch in candidates:
                try:
                    if batch.merged_pdf_path:
                        adapter.delete(batch.merged_pdf_path)
                except Exception as exc:
                    logger.warning(f"[retention_service] Failed to delete stored PDF for {batch.batch_no}: {exc}")

                batch.is_archived = True
                batch.archived_at = datetime.now(timezone.utc)
                archived_count += 1

            db.commit()

        if archived_count:
            logger.info(f"[retention_service] Archived {archived_count} batch(es)")
        return archived_count
    finally:
        db.close()


async def start_retention_archiver() -> None:
    """Background task: periodically archive old batches per RETENTION_CHECK_INTERVAL_SECONDS."""
    logger.info(
        f"[retention_service] Retention archiver started — interval={settings.RETENTION_CHECK_INTERVAL_SECONDS}s"
    )
    try:
        while True:
            try:
                await asyncio.to_thread(archive_old_batches)
            except Exception as exc:
                logger.error(f"[retention_service] Archival cycle failed: {exc}")

            await asyncio.sleep(settings.RETENTION_CHECK_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("[retention_service] Retention archiver stopped")
        raise
