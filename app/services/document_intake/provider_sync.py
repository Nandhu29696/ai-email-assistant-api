"""Scheduled document-intake synchronization for Outlook Graph and IMAP."""
from __future__ import annotations
from loguru import logger
from app.database import SessionLocal
from app.models.email import EmailIntegration
from app.services.document_intake.pipeline import process_document_intake_email
from app.services.document_intake.provider_adapters import OutlookGraphAdapter, IMAPDocumentAdapter


async def sync_all_document_providers() -> int:
    db = SessionLocal()
    try:
        integrations = (
            db.query(EmailIntegration)
            .filter(
                EmailIntegration.is_active == True,
                EmailIntegration.processing_mode.in_(("document_intake", "both")),
                EmailIntegration.provider.in_(("outlook", "imap")),
            )
            .all()
        )
        integration_ids = [i.id for i in integrations]
    finally:
        db.close()

    processed = 0
    for integration_id in integration_ids:
        db = SessionLocal()
        integration = db.query(EmailIntegration).filter(EmailIntegration.id == integration_id).first()
        db.close()
        if not integration:
            continue

        try:
            adapter = OutlookGraphAdapter(integration) if integration.provider == "outlook" else IMAPDocumentAdapter(integration)
            if integration.provider == "outlook":
                contexts = [(adapter.build_context(message), message) for message in adapter.fetch_unseen()]
            else:
                contexts = adapter.fetch_contexts()

            for context, _raw in contexts:
                await process_document_intake_email(integration_id, adapter, context)
                processed += 1
        except Exception as exc:
            logger.error(f"[provider_sync] {integration.provider} integration {integration_id} failed: {exc}")

    if processed:
        logger.info(f"[provider_sync] Processed {processed} Outlook/IMAP document message(s)")
    return processed
