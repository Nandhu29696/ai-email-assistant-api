import asyncio
from datetime import datetime, timezone

from app.routers.integrations import _oauth_state, _oauth_user_id
from app.models.user import User
from app.models.email import EmailIntegration
from app.models.document_intake import EmailBatch
from app.services.document_intake import pipeline


def test_oauth_state_binds_provider_user_and_is_single_use(db_session):
    user = User(
        id=42,
        username="owner",
        email="owner@example.com",
        hashed_password="test-hash",
        role="client",
    )
    db_session.add(user)
    db_session.commit()
    state = _oauth_state(db_session, user, "gmail")

    assert _oauth_user_id(db_session, state, "gmail") == 42
    assert _oauth_user_id(db_session, state, "gmail") is None
    assert _oauth_user_id(db_session, state, "outlook") is None
    assert _oauth_user_id(db_session, None, "gmail") is None


def test_document_intake_skips_existing_integration_message(db_session, monkeypatch):
    integration = EmailIntegration(
        provider="gmail",
        email_address="intake@example.com",
    )
    db_session.add(integration)
    db_session.flush()
    db_session.add(EmailBatch(
        batch_no="TEST-000001",
        message_id="gmail-message-1",
        integration_id=integration.id,
        sender_email="sender@example.com",
        received_datetime=datetime.now(timezone.utc),
        status="SUCCESS",
    ))
    db_session.commit()
    monkeypatch.setattr(pipeline, "SessionLocal", lambda: db_session)

    result = asyncio.run(pipeline.process_document_intake_email(
        integration.id,
        service=object(),
        ctx=pipeline.IntakeEmailContext(
            gmail_message_id="gmail-message-1",
            stored_message_id="gmail-message-1",
            thread_id=None,
            headers={},
            sender_name="Sender",
            sender_email="sender@example.com",
            recipient_email="intake@example.com",
            subject="Duplicate",
            received_at=datetime.now(timezone.utc),
            payload={},
        ),
    ))

    assert result == "SUCCESS"
    assert db_session.query(EmailBatch).count() == 1