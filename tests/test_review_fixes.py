"""Regression tests for issues found in the project review."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.email import EmailIntegration
from app.models.document_intake import EmailBatch
from app.models.user import User, UserSession
from app.routers.auth import hash_password, get_current_user
from app.services.document_intake.attachment_extractor import has_attachments
from app.services.document_intake.template_renderer import render_template


@pytest.fixture()
def client(db_session, monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "_seed_templates", lambda: None)
    monkeypatch.setattr(main_module.settings, "RUN_BACKGROUND_WORKERS", False)
    main_module.app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(main_module.app) as test_client:
        yield test_client
    main_module.app.dependency_overrides.clear()


def _user(db, username, role="client", password="Sup3rSecret99"):
    user = User(username=username, email=f"{username}@example.com",
                hashed_password=hash_password(password), role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── #2 Outlook webhook validates clientState ─────────────────
def test_outlook_webhook_rejects_bad_client_state(client, monkeypatch):
    from app.routers import integrations
    monkeypatch.setattr(integrations.settings, "OUTLOOK_WEBHOOK_CLIENT_STATE", "expected-secret")
    response = client.post("/api/integrations/outlook/webhook", json={"value": [{"clientState": "wrong"}]})
    assert response.status_code == 401


def test_outlook_webhook_validation_handshake(client):
    response = client.post("/api/integrations/outlook/webhook?validationToken=abc123")
    assert response.status_code == 200
    assert response.text == "abc123"


# ── #6 template values are HTML-escaped ───────────────────────
def test_template_context_is_html_escaped(db_session):
    from app.services.document_intake.template_renderer import file_list_html

    rendered = render_template(
        db_session, "domain_rejected",
        context={"subject": "<b>hi</b>", "domain": '<a href="https://evil">x</a>'},
    )
    assert "<a href" not in rendered.html_body
    assert "&lt;a href" in rendered.html_body
    listed = file_list_html([('<img src=x onerror=alert(1)>.pdf', "<script>")])
    assert "<img" not in listed and "&lt;script&gt;" in listed


# ── #7 untargeted notifications reach admins only ─────────────

# ── #9 datetimes come back timezone-aware on every backend ────
def test_datetimes_round_trip_as_aware_utc(db_session):
    user = _user(db_session, "tz")
    user.locked_until = datetime.now(timezone(timedelta(hours=5, minutes=30))) + timedelta(minutes=5)
    db_session.commit()
    db_session.expire_all()
    fetched = db_session.query(User).filter(User.id == user.id).one()
    assert fetched.locked_until.tzinfo is not None
    assert fetched.locked_until > datetime.now(timezone.utc)  # would raise TypeError if naive


def test_login_refresh_and_multiple_sessions(client, db_session):
    _user(db_session, "alice", password="Sup3rSecret99")
    token_mode = {"X-Auth-Mode": "token"}  # API-client mode: tokens in the JSON body
    first = client.post("/api/auth/login", data={"username": "alice", "password": "Sup3rSecret99"}, headers=token_mode)
    second = client.post("/api/auth/login", data={"username": "alice", "password": "Sup3rSecret99"}, headers=token_mode)
    assert first.status_code == 200 and second.status_code == 200

    # Both sessions stay valid (one per device) and tokens are stored hashed.
    sessions = db_session.query(UserSession).filter(UserSession.is_active == True).all()  # noqa: E712
    assert len(sessions) == 2
    assert all(s.refresh_token != first.json()["refresh_token"] for s in sessions)

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": first.json()["refresh_token"]})
    assert refreshed.status_code == 200
    reused = client.post("/api/auth/refresh", json={"refresh_token": first.json()["refresh_token"]})
    assert reused.status_code == 401


def test_register_default_role_is_valid(client, db_session):
    admin = _user(db_session, "boss", role="admin")
    import app.main as main_module
    main_module.app.dependency_overrides[get_current_user] = lambda: admin
    response = client.post("/api/auth/register", json={
        "username": "newbie", "email": "newbie@example.com", "password": "Sup3rSecret99",
    })
    assert response.status_code == 201
    assert response.json()["role"] == "client"


# ── #11 inline signature images are not attachments ───────────
def test_inline_images_are_not_attachments():
    signature_only = {"parts": [
        {"mimeType": "text/html", "body": {"data": "aGk="}},
        {"mimeType": "image/png", "filename": "image001.png", "body": {"attachmentId": "x"},
         "headers": [{"name": "Content-Disposition", "value": "inline; filename=image001.png"},
                     {"name": "Content-ID", "value": "<image001>"}]},
    ]}
    assert has_attachments(signature_only) is False

    with_pdf = {"parts": signature_only["parts"] + [
        {"mimeType": "application/pdf", "filename": "doc.pdf", "body": {"attachmentId": "y"},
         "headers": [{"name": "Content-Disposition", "value": "attachment; filename=doc.pdf"}]},
    ]}
    assert has_attachments(with_pdf) is True


# ── #15 storage paths resolve for legacy and new rows ─────────
def test_local_storage_accepts_saved_and_legacy_paths(tmp_path, monkeypatch):
    from app.services.document_intake.storage import local_disk

    adapter = local_disk.LocalDiskStorageAdapter(base_path=str(tmp_path))
    saved = adapter.save("PROD/2026/09/X.pdf", b"%PDF")
    assert adapter.read(saved) == b"%PDF"
    adapter.delete(saved)
    assert not (tmp_path / "PROD/2026/09/X.pdf").exists()

    with pytest.raises(ValueError):
        adapter.read("../../etc/passwd")


# ── #22 same message in two mailboxes ─────────────────────────
def test_same_message_id_allowed_in_different_mailboxes(db_session):
    a = EmailIntegration(provider="gmail", email_address="a@example.com")
    b = EmailIntegration(provider="gmail", email_address="b@example.com")
    db_session.add_all([a, b])
    db_session.commit()
    for integration in (a, b):
        db_session.add(EmailBatch(batch_no=f"T-{integration.id}", message_id="shared@id", integration_id=integration.id,
                                  sender_email="x@example.com", received_datetime=datetime.now(timezone.utc)))
    db_session.commit()
    assert db_session.query(EmailBatch).filter(EmailBatch.message_id == "shared@id").count() == 2
