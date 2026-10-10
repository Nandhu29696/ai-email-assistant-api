"""Per-mailbox views: filters, mailbox fields and the dashboard's per-mailbox table, scoped by user."""
# ruff: noqa: F811  (pytest fixtures imported from another test module)
from datetime import datetime, timedelta, timezone

import pytest

from app.models.document_intake import EmailBatch
from app.models.email import EmailIntegration
from tests.test_enhancements import _csrf, _login, _user, client  # noqa: F401


@pytest.fixture()
def two_mailboxes(db_session):
    owner_a = _user(db_session, "owner_a")
    owner_b = _user(db_session, "owner_b")
    _user(db_session, "boss", role="admin")
    a = EmailIntegration(provider="gmail", email_address="claims@ours.com", owner_user_id=owner_a.id,
                         is_active=True, health_status="healthy", batch_prefix="CLM")
    b = EmailIntegration(provider="outlook", email_address="invoices@ours.com", owner_user_id=owner_b.id,
                         is_active=True, health_status="error", health_message="Token expired")
    db_session.add_all([a, b])
    db_session.commit()
    now = datetime.now(timezone.utc)
    rows = [(a, "SUCCESS"), (a, "SUCCESS"), (a, "REJECTED"), (a, "FAILED"), (b, "SUCCESS"), (b, "IGNORED")]
    for n, (box, status) in enumerate(rows):
        db_session.add(EmailBatch(batch_no=f"MB-{n}", message_id=f"<mb{n}>", integration_id=box.id,
                                  sender_email="x@client.com", recipient_email="alias@ours.com",
                                  received_datetime=now - timedelta(hours=n), processed_at=now - timedelta(hours=n),
                                  status=status))
    db_session.commit()
    return a, b


def test_email_list_has_mailbox_fields_and_filter(client, db_session, two_mailboxes):
    a, b = two_mailboxes
    _login(client, "boss")
    all_items = client.get("/api/document-intake/batches", params={"page_size": 100}).json()
    assert all_items["total"] == 6
    first = all_items["items"][0]
    assert first["integration_id"] == a.id and first["mailbox_email"] == "claims@ours.com" and first["mailbox_provider"] == "gmail"
    only_b = client.get("/api/document-intake/batches", params={"integration_id": b.id}).json()
    assert only_b["total"] == 2 and {i["mailbox_email"] for i in only_b["items"]} == {"invoices@ours.com"}
    feed = client.get("/api/document-intake/activity", params={"integration_id": a.id}).json()
    assert len(feed["items"]) == 4 and all(i["integration_id"] == a.id for i in feed["items"])


def test_admin_dashboard_per_mailbox_table_and_filter(client, db_session, two_mailboxes):
    a, b = two_mailboxes
    _login(client, "boss")
    data = client.get("/api/dashboard/summary").json()
    assert data["total"] == 6
    table = {m["email_address"]: m for m in data["by_mailbox"]}
    assert table["claims@ours.com"]["total"] == 4
    assert (table["claims@ours.com"]["processed"], table["claims@ours.com"]["rejected"],
            table["claims@ours.com"]["needs_attention"]) == (2, 1, 1)
    assert table["claims@ours.com"]["owner"] == "owner_a" and table["claims@ours.com"]["last_email_at"]
    assert table["invoices@ours.com"]["ignored"] == 1 and table["invoices@ours.com"]["health_status"] == "error"

    only_a = client.get("/api/dashboard/summary", params={"integration_id": a.id}).json()
    assert only_a["total"] == 4 and only_a["by_status"] == {"SUCCESS": 2, "REJECTED": 1, "FAILED": 1}
    assert len(only_a["by_mailbox"]) == 2                      # the overview table still lists every mailbox
    assert [m["email_address"] for m in only_a["pickup"]["mailboxes"]] == ["claims@ours.com"]


def test_client_only_sees_own_mailbox_even_when_asking_for_another(client, db_session, two_mailboxes):
    a, b = two_mailboxes
    _login(client, "owner_a")
    data = client.get("/api/dashboard/summary").json()
    assert data["total"] == 4 and [m["email_address"] for m in data["by_mailbox"]] == ["claims@ours.com"]
    other = client.get("/api/dashboard/summary", params={"integration_id": b.id}).json()
    assert other["total"] == 0
    assert client.get("/api/document-intake/batches", params={"integration_id": b.id}).json()["total"] == 0


def test_disconnected_mailbox_with_history_stays_visible(client, db_session, two_mailboxes):
    a, b = two_mailboxes
    b.is_active = False
    db_session.commit()
    _login(client, "boss")
    data = client.get("/api/dashboard/summary").json()
    table = {m["email_address"]: m for m in data["by_mailbox"]}
    assert table["invoices@ours.com"]["is_active"] is False and table["invoices@ours.com"]["total"] == 2
    assert "invoices@ours.com" not in [m["email_address"] for m in data["pickup"]["mailboxes"]]


def test_status_totals_always_add_up(client, db_session, two_mailboxes):
    _login(client, "boss")
    data = client.get("/api/dashboard/summary").json()
    totals = data["status_totals"]
    assert totals == {"processed": 3, "rejected": 1, "needs_attention": 1, "ignored": 1, "in_progress": 0, "other": 0}
    assert sum(totals.values()) == data["total"] == 6
    per_day = data["daily"]
    assert sum(d["IGNORED"] for d in per_day) == 1 and all("IN_PROGRESS" in d for d in per_day)
    assert sum(d["SUCCESS"] + d["REJECTED"] + d["FAILED"] + d["IGNORED"] + d["IN_PROGRESS"] + d["OTHER"] for d in per_day) == 6


def test_dashboard_monthly_totals_match_daily():
    from app.routers.dashboard import _monthly
    days = [
        {"date": "2026-09-29", "SUCCESS": 1, "REJECTED": 2, "FAILED": 0, "IGNORED": 0, "IN_PROGRESS": 0, "OTHER": 0},
        {"date": "2026-09-30", "SUCCESS": 0, "REJECTED": 1, "FAILED": 1, "IGNORED": 0, "IN_PROGRESS": 0, "OTHER": 0},
        {"date": "2026-10-02", "SUCCESS": 2, "REJECTED": 0, "FAILED": 0, "IGNORED": 3, "IN_PROGRESS": 1, "OTHER": 0},
    ]
    assert _monthly(days) == [
        {"month": "2026-09", "SUCCESS": 1, "REJECTED": 3, "FAILED": 1, "IGNORED": 0, "IN_PROGRESS": 0, "OTHER": 0},
        {"month": "2026-10", "SUCCESS": 2, "REJECTED": 0, "FAILED": 0, "IGNORED": 3, "IN_PROGRESS": 1, "OTHER": 0},
    ]


def test_dashboard_monthly_fills_empty_months():
    from datetime import datetime, timezone

    from app.routers.dashboard import _first_of_month, _monthly
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    start = _first_of_month(5, now)
    assert start == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert _first_of_month(10, now) == datetime(2025, 12, 1, tzinfo=timezone.utc)
    rows = _monthly([{"date": "2026-09-03", "SUCCESS": 2}], start, now)
    assert [r["month"] for r in rows] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    assert rows[4]["SUCCESS"] == 2 and sum(r["SUCCESS"] for r in rows) == 2


def test_email_list_mailbox_type_filter(client, db_session, two_mailboxes):
    a, _ = two_mailboxes
    for batch in db_session.query(EmailBatch).filter(EmailBatch.batch_no.in_(["MB-0", "MB-1"])):
        batch.mailbox_type = "UAT"
    for batch in db_session.query(EmailBatch).filter(EmailBatch.batch_no.notin_(["MB-0", "MB-1"])):
        batch.mailbox_type = "PROD"
    db_session.commit()
    _login(client, "boss")
    uat = client.get("/api/document-intake/batches", params={"mailbox_type": "UAT"}).json()
    assert uat["total"] == 2 and {i["mailbox_type"] for i in uat["items"]} == {"UAT"}
    assert client.get("/api/document-intake/batches", params={"mailbox_type": "PROD", "integration_id": a.id}).json()["total"] == 2
    assert client.get("/api/document-intake/batches", params={"mailbox_type": "DEV"}).json()["total"] == 0
    assert client.get("/api/document-intake/batches", params={"mailbox_type": "bogus"}).status_code == 422


def test_mailbox_pickup_interval_setting(client, db_session, two_mailboxes):
    from app.config import settings
    a, _ = two_mailboxes
    _login(client, "boss")
    box = next(m for m in client.get("/api/integrations").json() if m["id"] == a.id)
    assert box["fetch_interval_seconds"] is None
    assert box["pickup_interval_seconds"] == box["default_pickup_interval_seconds"] == max(15, settings.FETCH_INTERVAL_SECONDS)

    assert client.patch(f"/api/integrations/{a.id}", headers=_csrf(client), json={"fetch_interval_seconds": 10}).status_code == 422
    assert client.patch(f"/api/integrations/{a.id}", headers=_csrf(client), json={"fetch_interval_seconds": 3601}).status_code == 422
    assert client.patch(f"/api/integrations/{a.id}", headers=_csrf(client), json={"fetch_interval_seconds": 20}).status_code == 200
    box = next(m for m in client.get("/api/integrations").json() if m["id"] == a.id)
    assert box["fetch_interval_seconds"] == 20 and box["pickup_interval_seconds"] == 20
    summary = client.get("/api/dashboard/summary", params={"integration_id": a.id}).json()
    assert summary["pickup"]["mailboxes"][0]["interval_seconds"] == 20

    assert client.patch(f"/api/integrations/{a.id}", headers=_csrf(client), json={"fetch_interval_seconds": None}).status_code == 200
    db_session.expire_all()
    assert db_session.get(EmailIntegration, a.id).fetch_interval_seconds is None


def test_scheduler_uses_each_mailbox_interval(db_session, two_mailboxes, monkeypatch):
    import asyncio

    from sqlalchemy.orm import sessionmaker

    from app.jobs import tasks
    a, b = two_mailboxes
    now = datetime.now(timezone.utc)
    a.fetch_interval_seconds, a.last_sync_at = 20, now - timedelta(seconds=30)    # due
    b.fetch_interval_seconds, b.last_sync_at = 600, now - timedelta(seconds=30)   # not due yet
    b.access_token = a.access_token = "token"
    db_session.commit()

    queued = []

    async def fake_enqueue(name, integration_id, job_id=None):
        queued.append(integration_id)
        return "queued"

    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    monkeypatch.setattr(tasks, "enqueue", fake_enqueue)
    assert asyncio.run(tasks.schedule_mailbox_syncs()) == 1 and queued == [a.id]


def test_email_list_status_tabs_and_counts(client, db_session, two_mailboxes):
    a, _ = two_mailboxes
    db_session.add(EmailBatch(batch_no="MB-P", message_id="<mbp>", integration_id=a.id, sender_email="x@client.com",
                              recipient_email="alias@ours.com", received_datetime=datetime.now(timezone.utc), status="PROCESSING"))
    db_session.commit()
    _login(client, "boss")
    data = client.get("/api/document-intake/batches", params={"status": "REJECTED"}).json()
    assert data["total"] == 1
    # counts ignore the status filter itself, so every tab shows its own number
    assert data["status_counts"] == {"ALL": 7, "SUCCESS": 3, "REJECTED": 1, "FAILED": 1, "IGNORED": 1, "IN_PROGRESS": 1}
    in_progress = client.get("/api/document-intake/batches", params={"status": "IN_PROGRESS"}).json()
    assert [i["batch_no"] for i in in_progress["items"]] == ["MB-P"]
    only_a = client.get("/api/document-intake/batches", params={"integration_id": a.id}).json()["status_counts"]
    assert only_a["ALL"] == 5 and only_a["SUCCESS"] == 2
