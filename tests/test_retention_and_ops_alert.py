import asyncio
from datetime import datetime, timedelta, timezone

from app.services.document_intake.batch_id_generator import generate_batch_no
from app.services.document_intake.retention_service import archive_old_batches
from app.services.document_intake.ops_alert_service import send_ops_alert
from app.models.email import EmailIntegration
from app.models.document_intake import EmailBatch


def test_generate_batch_no_format_and_sequence_increment(db_session):
    first = generate_batch_no(db_session, "CRS", "PROD")
    db_session.commit()
    second = generate_batch_no(db_session, "CRS", "PROD")
    db_session.commit()

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert first == f"CRS-PROD-{today}-000001"
    assert second == f"CRS-PROD-{today}-000002"


def test_generate_batch_no_different_prefix_has_independent_sequence(db_session):
    a = generate_batch_no(db_session, "CRS", "PROD")
    db_session.commit()
    b = generate_batch_no(db_session, "INV", "PROD")
    db_session.commit()
    assert a.startswith("CRS-")
    assert b.startswith("INV-")
    assert a.split("-")[-1] == "000001"
    assert b.split("-")[-1] == "000001"


def test_archive_old_batches_flags_stale_success_batches(db_session, monkeypatch):
    integration = EmailIntegration(
        provider="gmail", email_address="intake@example.com", retention_days=30,
        storage_provider="local",
    )
    db_session.add(integration)
    db_session.commit()
    db_session.refresh(integration)

    old_processed = datetime.now(timezone.utc) - timedelta(days=60)
    batch = EmailBatch(
        batch_no="CRS-PROD-20260101-000001",
        message_id="msg-1",
        integration_id=integration.id,
        mailbox_type="PROD",
        sender_email="client@example.com",
        received_datetime=old_processed,
        status="SUCCESS",
        processed_at=old_processed,
        merged_pdf_path=None,
    )
    db_session.add(batch)
    db_session.commit()

    # Patch SessionLocal used inside the service to reuse our test session/engine
    import app.services.document_intake.retention_service as retention_module
    monkeypatch.setattr(retention_module, "SessionLocal", lambda: db_session)

    # Prevent the real session.close() (used by the service's `finally`) from closing our fixture session
    monkeypatch.setattr(db_session, "close", lambda: None)

    archived = archive_old_batches()
    assert archived == 1

    db_session.refresh(batch)
    assert batch.is_archived is True
    assert batch.archived_at is not None


def test_send_ops_alert_does_not_raise_without_webhook_configured():
    # No OPS_ALERT_WEBHOOK_URL configured by default — should just broadcast in-app and return.
    asyncio.run(send_ops_alert("Test Alert", "Something failed", details={"k": "v"}))
