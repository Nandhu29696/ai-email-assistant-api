# ruff: noqa: F811  (pytest fixtures imported from other test modules)
"""Tier-1 features: retention, AI summary, priority, ops alerts, per-mailbox reply texts and test emails."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from pypdf import PdfReader

from app.models.document_intake import EmailBatch, EmailBatchAttachment, EmailBatchEvent, EmailTemplate
from app.models.email import EmailIntegration
from app.services import ops_alert
from app.services.document_intake import pipeline
from app.services.document_intake.retention_service import archive_old_batches
from tests.test_enhancements import _csrf, _login, _user, client  # noqa: F401  (client is a fixture)
from tests.test_intake_flow import FakeMailbox, att, env, make_pdf, run  # noqa: F401  (env is a fixture)


# ── 1. Retention ──────────────────────────────────────────────
def _stored_batch(db, mailbox_id, root, name, days_ago):
    folder = root / name
    folder.mkdir(parents=True)
    paths = {k: folder / f"{k}.pdf" for k in ("merged", "email", "att")}
    for p in paths.values():
        p.write_bytes(b"%PDF")
    batch = EmailBatch(batch_no=name, message_id=f"<{name}>", integration_id=mailbox_id, sender_email="a@client.com",
                       received_datetime=datetime.now(timezone.utc) - timedelta(days=days_ago), status="SUCCESS",
                       outcome="PROCESSED", processed_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
                       merged_pdf_path=str(paths["merged"]), email_pdf_path=str(paths["email"]))
    db.add(batch)
    db.flush()
    db.add(EmailBatchAttachment(parent_batch_id=batch.id, batch_no=name, batch_source_filename="a.pdf",
                                status="MERGED", converted_pdf_path=str(paths["att"])))
    db.commit()
    return batch.id, paths


def test_retention_deletes_all_pdfs_of_old_emails_and_keeps_the_record(db_session, tmp_path, monkeypatch):
    from app.services.document_intake import retention_service
    monkeypatch.setattr(retention_service, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(retention_service.settings, "DOCUMENT_INTAKE_LOCAL_PATH", str(tmp_path))
    default_box = EmailIntegration(provider="gmail", email_address="keep90@example.com")          # default 90 days
    short_box = EmailIntegration(provider="gmail", email_address="keep5@example.com", retention_days=5)
    db_session.add_all([default_box, short_box])
    db_session.commit()

    old_id, old_paths = _stored_batch(db_session, default_box.id, tmp_path, "OLD-1", days_ago=120)
    recent_id, recent_paths = _stored_batch(db_session, default_box.id, tmp_path, "NEW-1", days_ago=10)
    short_id, short_paths = _stored_batch(db_session, short_box.id, tmp_path, "SHORT-1", days_ago=10)

    assert archive_old_batches() == 2

    old = db_session.get(EmailBatch, old_id)
    assert old.is_archived and old.archived_at and old.merged_pdf_path is None and old.email_pdf_path is None
    assert all(not p.exists() for p in old_paths.values())
    assert db_session.query(EmailBatchAttachment).filter_by(parent_batch_id=old_id).one().converted_pdf_path is None
    event = db_session.query(EmailBatchEvent).filter_by(parent_batch_id=old_id, event_type="ARCHIVED").one()
    assert event.details["files_deleted"] == 3 and old.outcome == "PROCESSED"     # the record is kept

    assert db_session.get(EmailBatch, short_id).is_archived                      # mailbox override: 5 days
    assert not db_session.get(EmailBatch, recent_id).is_archived and all(p.exists() for p in recent_paths.values())
    assert archive_old_batches() == 0                                            # idempotent


# ── 2 + 3. AI summary and priority ────────────────────────────
def test_every_email_gets_priority_and_summary_and_the_summary_is_on_the_email_pdf(env):
    db, mailbox, _ = env
    service = FakeMailbox([att("invoice.pdf", make_pdf())])
    body = ("This is the third time I am writing. I was charged twice for order 7781 and nobody answered. "
            "I want a refund immediately, this is unacceptable!")
    status, batch = run(db, mailbox, service, body=body)
    assert status == "SUCCESS"
    assert batch.priority in ("high", "critical")
    assert batch.ai_summary and "charged twice" in batch.ai_summary
    email_pdf_text = "".join(p.extract_text() for p in PdfReader(batch.email_pdf_path).pages)
    assert "Summary:" in email_pdf_text

    _, calm = run(db, mailbox, FakeMailbox(), body="Thanks a lot for the great service, everything is fine.")
    assert calm.priority == "low"


# ── 4. Ops alerts ─────────────────────────────────────────────
@pytest.fixture()
def alerts(monkeypatch):
    sent = []

    class Response:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(ops_alert.settings, "OPS_ALERT_WEBHOOK_URL", "https://hooks.example.com/x")
    monkeypatch.setattr(ops_alert.httpx, "post", lambda url, json, timeout: sent.append(json["text"]) or Response())
    return sent


def test_failed_email_raises_an_alert(env, alerts, monkeypatch):
    db, mailbox, _ = env

    class BrokenStorage:
        def save(self, path, data):
            raise OSError("disk full")
    monkeypatch.setattr(pipeline, "get_storage_adapter", lambda: BrokenStorage())
    status, batch = run(db, mailbox, FakeMailbox([att("a.pdf", make_pdf())]))
    assert status == "FAILED"
    assert len(alerts) == 1 and batch.batch_no in alerts[0] and "disk full" in alerts[0]


def test_rule_rejections_do_not_alert(env, alerts):
    db, mailbox, _ = env
    run(db, mailbox, FakeMailbox(), sender="x@unknown.org")
    run(db, mailbox, FakeMailbox())
    assert alerts == []


def test_mailbox_alerts_only_when_it_becomes_broken(alerts, monkeypatch):
    class InlineThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)
    monkeypatch.setattr(ops_alert.threading, "Thread", InlineThread)

    ops_alert.mailbox_health_changed("box@example.com", "healthy", "error", "Token revoked")
    ops_alert.mailbox_health_changed("box@example.com", "error", "error", "Token revoked")     # still broken
    ops_alert.mailbox_health_changed("box@example.com", "error", "healthy", "ok")              # recovered
    assert len(alerts) == 1 and "box@example.com" in alerts[0] and "Token revoked" in alerts[0]


def test_alerts_are_off_without_a_webhook(monkeypatch):
    monkeypatch.setattr(ops_alert.settings, "OPS_ALERT_WEBHOOK_URL", "")
    assert ops_alert.send_ops_alert("t", "m") is False


def test_admin_test_alert_endpoint(client, db_session, alerts):
    _user(db_session, "alertadmin", role="admin")
    _login(client, "alertadmin")
    response = client.post("/api/admin/ops-alert/test", headers=_csrf(client))
    assert response.status_code == 200 and "Test alert" in alerts[0]


# ── 5. Per-mailbox reply texts and test emails ────────────────
def test_mailbox_override_does_not_change_other_mailboxes(client, db_session):
    _user(db_session, "tpladmin", role="admin")
    a = EmailIntegration(provider="gmail", email_address="a@ours.com", is_active=True)
    b = EmailIntegration(provider="gmail", email_address="b@ours.com", is_active=True)
    db_session.add_all([a, b])
    db_session.commit()
    _login(client, "tpladmin")
    headers = _csrf(client)

    saved = client.put(f"/api/document-intake/templates/acknowledgement?integration_id={a.id}", headers=headers,
                       json={"subject_template": "Re: $subject — Thanks from Team A"})
    assert saved.status_code == 200 and saved.json()["is_override"] is True

    listed_a = {t["template_key"]: t for t in client.get(f"/api/document-intake/templates?integration_id={a.id}").json()}
    listed_b = {t["template_key"]: t for t in client.get(f"/api/document-intake/templates?integration_id={b.id}").json()}
    global_ = {t["template_key"]: t for t in client.get("/api/document-intake/templates").json()}
    assert listed_a["acknowledgement"]["subject_template"].endswith("Thanks from Team A")
    assert listed_b["acknowledgement"]["is_override"] is False
    assert "Thanks from Team A" not in listed_b["acknowledgement"]["subject_template"]
    assert "Thanks from Team A" not in global_["acknowledgement"]["subject_template"]

    preview = client.get(f"/api/document-intake/templates/acknowledgement/preview?integration_id={a.id}").json()
    assert preview["subject"] == "Re: Claim documents — Thanks from Team A"

    reset = client.post(f"/api/document-intake/templates/acknowledgement/reset?integration_id={a.id}", headers=headers)
    assert reset.json()["is_override"] is False
    assert db_session.query(EmailTemplate).filter_by(integration_id=a.id).count() == 0


def test_send_test_email_uses_the_mailbox_and_its_override(client, db_session, monkeypatch):
    from app.services import mail_sender
    _user(db_session, "testsender", role="admin")
    box = EmailIntegration(provider="gmail", email_address="intake@ours.com", is_active=True)
    db_session.add(box)
    db_session.commit()
    _login(client, "testsender")
    headers = _csrf(client)
    client.put(f"/api/document-intake/templates/success?integration_id={box.id}", headers=headers,
               json={"subject_template": "Re: $subject — All done (Team A)"})

    sent = []
    monkeypatch.setattr(mail_sender, "send_new_message", lambda mid, to, subject, html: sent.append((mid, to, subject, html)))
    response = client.post("/api/document-intake/templates/success/test", headers=headers, json={"integration_id": box.id})
    assert response.status_code == 200, response.text
    mid, to, subject, html = sent[0]
    assert mid == box.id and to == "intake@ours.com"
    assert subject == "[TEST] Re: Claim documents — All done (Team A)" and "invoice.pdf" in html

    other = client.post("/api/document-intake/templates/success/test", headers=headers,
                        json={"integration_id": box.id, "to": "qa@example.com"})
    assert other.status_code == 200 and sent[1][1] == "qa@example.com"

    def fail(*args):
        raise mail_sender.MailSendError("This mailbox is not connected")
    monkeypatch.setattr(mail_sender, "send_new_message", fail)
    failed = client.post("/api/document-intake/templates/success/test", headers=headers, json={"integration_id": box.id})
    assert failed.status_code == 502 and "not connected" in failed.json()["detail"]


def test_only_admins_can_edit_or_send_templates(client, db_session):
    _user(db_session, "plainclient")
    _login(client, "plainclient")
    headers = _csrf(client)
    assert client.put("/api/document-intake/templates/success", headers=headers, json={"subject_template": "x"}).status_code == 403
    assert client.post("/api/document-intake/templates/success/test", headers=headers, json={"integration_id": 1}).status_code == 403


def test_mailbox_retention_setting_is_validated(client, db_session):
    owner = _user(db_session, "retowner")
    box = EmailIntegration(provider="gmail", email_address="ret@example.com", owner_user_id=owner.id)
    db_session.add(box)
    db_session.commit()
    _login(client, "retowner")
    assert client.patch(f"/api/integrations/{box.id}", headers=_csrf(client), json={"retention_days": 0}).status_code == 422
    assert client.patch(f"/api/integrations/{box.id}", headers=_csrf(client), json={"retention_days": 30}).status_code == 200
    db_session.refresh(box)
    assert box.retention_days == 30


def test_mail_sender_refuses_disconnected_mailboxes(db_session, monkeypatch):
    from app.services import mail_sender
    monkeypatch.setattr(mail_sender, "SessionLocal", lambda: db_session)
    box = EmailIntegration(provider="gmail", email_address="off@ours.com", is_active=False)
    db_session.add(box)
    db_session.commit()
    with pytest.raises(mail_sender.MailSendError, match="not connected"):
        asyncio.run(asyncio.to_thread(mail_sender.send_new_message, box.id, "x@example.com", "s", "<p>h</p>"))


# ── Summary edge cases ────────────────────────────────────────
def test_short_emails_are_their_own_summary_and_off_topic_answers_are_rejected(monkeypatch):
    from app.services import summarizer

    calls = []

    async def model(subject, body, thread_context=None):
        calls.append(body)
        return "There is no email content provided to summarize. The text appears to be a placeholder."
    monkeypatch.setattr(summarizer, "ai_available", lambda: True)
    monkeypatch.setattr(summarizer, "_openai_summarize", model)

    assert asyncio.run(summarizer.generate_summary("Hello", "Hello")) == "Hello"
    assert calls == []                                    # short email: no model call
    long_body = ("I was charged twice for order 7781 and nobody answered my emails. " * 4).strip()
    summary = asyncio.run(summarizer.generate_summary("Refund", long_body))
    assert "placeholder" not in summary and "charged twice" in summary   # off-topic answer replaced


def test_no_db_connection_is_held_during_slow_steps(env, monkeypatch):
    """UAT MySQL drops connections idle for 20s; slow steps must not hold one."""
    db, mailbox, _ = env
    checks = []
    real_slow = pipeline._slow

    async def watching(session, fn, *args):
        result = await real_slow(session, fn, *args)
        return result
    original_to_thread = pipeline.asyncio.to_thread

    async def to_thread(fn, *args):
        checks.append(db.in_transaction())
        return await original_to_thread(fn, *args)
    monkeypatch.setattr(pipeline.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(pipeline, "_slow", watching)
    status, _ = run(db, mailbox, FakeMailbox([att("a.pdf", make_pdf())]))
    assert status == "SUCCESS"
    assert checks and not any(checks), "a DB transaction was open while a slow step ran"


# ── Notification feed ─────────────────────────────────────────
def test_activity_feed_returns_recently_finished_emails_for_the_owner(client, db_session):
    owner = _user(db_session, "feedowner")
    other = _user(db_session, "feedother")
    mine = EmailIntegration(provider="gmail", email_address="mine@ours.com", owner_user_id=owner.id)
    theirs = EmailIntegration(provider="gmail", email_address="theirs@ours.com", owner_user_id=other.id)
    db_session.add_all([mine, theirs])
    db_session.commit()
    now = datetime.now(timezone.utc)
    for n, (box, minutes_ago, status) in enumerate([(mine, 30, "SUCCESS"), (mine, 2, "FAILED"), (theirs, 1, "SUCCESS")]):
        db_session.add(EmailBatch(batch_no=f"FEED-{n}", message_id=f"<feed{n}>", integration_id=box.id, sender_email="a@b.com",
                                  received_datetime=now, status=status, processed_at=now - timedelta(minutes=minutes_ago)))
    db_session.add(EmailBatch(batch_no="FEED-busy", message_id="<busy>", integration_id=mine.id, sender_email="a@b.com",
                              received_datetime=now, status="PROCESSING"))
    db_session.commit()
    _login(client, "feedowner")

    all_items = client.get("/api/document-intake/activity").json()
    assert [i["batch_no"] for i in all_items["items"]] == ["FEED-1", "FEED-0"]       # own, finished, newest first
    since = (now - timedelta(minutes=10)).isoformat()
    recent = client.get("/api/document-intake/activity", params={"since": since}).json()
    assert [i["batch_no"] for i in recent["items"]] == ["FEED-1"] and recent["server_time"]
