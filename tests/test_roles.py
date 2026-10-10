"""Role-based access: admin → client → user."""
# ruff: noqa: F811  (pytest fixtures imported from another test module)
from datetime import datetime, timezone

import pytest

from app.models.document_intake import EmailBatch
from app.models.email import EmailIntegration
from tests.test_enhancements import _csrf, _login, _user, client  # noqa: F401

PASSWORD = "Sup3rSecret99"


@pytest.fixture()
def accounts(db_session):
    """Two clients with one mailbox and one email each; acme has a staff user."""
    _user(db_session, "boss", role="admin")
    acme = _user(db_session, "acme")
    globex = _user(db_session, "globex")
    staff = _user(db_session, "acme_staff", role="user")
    staff.client_id = acme.id
    boxes = {}
    for owner, address in ((acme, "in@acme.com"), (globex, "in@globex.com")):
        box = EmailIntegration(provider="imap", email_address=address, owner_user_id=owner.id, is_active=True)
        db_session.add(box)
        db_session.flush()
        db_session.add(EmailBatch(batch_no=f"B-{owner.username}", message_id=f"<{owner.username}>", integration_id=box.id,
                                  sender_email="x@c.com", recipient_email=address, status="SUCCESS",
                                  received_datetime=datetime.now(timezone.utc)))
        boxes[owner.username] = box
    db_session.commit()
    return {"acme": acme, "globex": globex, "staff": staff, **{f"box_{k}": v for k, v in boxes.items()}}


def _emails(client):
    return {i["batch_no"] for i in client.get("/api/document-intake/batches").json()["items"]}


def test_admin_sees_everything(client, accounts):
    _login(client, "boss")
    assert _emails(client) == {"B-acme", "B-globex"}
    assert {m["email_address"] for m in client.get("/api/integrations").json()} == {"in@acme.com", "in@globex.com"}


def test_user_sees_exactly_its_clients_data(client, accounts):
    _login(client, "acme_staff")
    assert _emails(client) == {"B-acme"}
    assert [m["email_address"] for m in client.get("/api/integrations").json()] == ["in@acme.com"]
    assert client.get("/api/dashboard/summary").json()["total"] == 1
    assert client.get("/api/document-intake/batches/B-globex").status_code == 404
    me = client.get("/api/auth/me").json()
    assert me["role"] == "user" and me["client_id"] == accounts["acme"].id and me["client_name"] == "acme"


def test_user_manages_its_clients_mailboxes_like_the_client(client, accounts):
    _login(client, "acme_staff")
    acme_box, globex_box = accounts["box_acme"], accounts["box_globex"]
    assert client.patch(f"/api/integrations/{acme_box.id}", headers=_csrf(client),
                        json={"max_file_size_mb": 10}).status_code == 200
    assert client.patch(f"/api/integrations/{globex_box.id}", headers=_csrf(client),
                        json={"max_file_size_mb": 10}).status_code == 403
    # cannot hand the mailbox to someone else
    assert client.patch(f"/api/integrations/{acme_box.id}", headers=_csrf(client),
                        json={"owner_user_id": accounts["globex"].id}).status_code == 403


def test_user_cannot_reach_admin_or_team_endpoints(client, accounts):
    _login(client, "acme_staff")
    for path in ("/api/admin/users", "/api/logs/audit", "/api/domains", "/api/team"):
        assert client.get(path).status_code == 403, path
    assert client.post("/api/team", headers=_csrf(client), json={
        "username": "sneaky", "email": "s@acme.com", "password": PASSWORD}).status_code == 403


def test_client_cannot_see_other_client_templates(client, accounts):
    _login(client, "acme")
    assert client.get("/api/document-intake/templates", params={"integration_id": accounts["box_globex"].id}).status_code == 404
    assert client.get("/api/document-intake/templates", params={"integration_id": accounts["box_acme"].id}).status_code == 200


def test_client_manages_its_own_team(client, db_session, accounts):
    _login(client, "acme")
    created = client.post("/api/team", headers=_csrf(client), json={
        "username": "acme_new", "email": "new@acme.com", "full_name": "New Hire", "password": PASSWORD})
    assert created.status_code == 201, created.text
    new = created.json()
    assert new["role"] == "user" and new["client_id"] == accounts["acme"].id
    assert {u["username"] for u in client.get("/api/team").json()} == {"acme_staff", "acme_new"}

    # cannot touch another client's or a non-member user
    assert client.patch(f"/api/team/{accounts['globex'].id}", headers=_csrf(client), json={"is_active": False}).status_code == 404
    assert client.patch(f"/api/team/{new['id']}", headers=_csrf(client), json={"full_name": "Renamed"}).json()["full_name"] == "Renamed"
    assert client.delete(f"/api/team/{new['id']}", headers=_csrf(client)).status_code == 200

    client.post("/api/auth/logout", headers=_csrf(client))
    assert client.post("/api/auth/login", data={"username": "acme_new", "password": PASSWORD}).status_code == 401


def test_deactivating_a_client_locks_out_its_users(client, db_session, accounts):
    _login(client, "acme_staff")
    assert client.get("/api/document-intake/batches").status_code == 200
    staff_client = client
    accounts["acme"].is_active = False
    db_session.commit()
    assert staff_client.get("/api/document-intake/batches").status_code == 401
    assert client.post("/api/auth/login", data={"username": "acme_staff", "password": PASSWORD}).status_code == 401


def test_admin_creates_user_for_a_client(client, accounts):
    _login(client, "boss")
    bad = client.post("/api/auth/register", headers=_csrf(client), json={
        "username": "orphan", "email": "o@x.com", "password": PASSWORD, "role": "user"})
    assert bad.status_code == 422
    not_client = client.post("/api/auth/register", headers=_csrf(client), json={
        "username": "orphan", "email": "o@x.com", "password": PASSWORD, "role": "user",
        "client_id": accounts["staff"].id})
    assert not_client.status_code == 422
    ok = client.post("/api/auth/register", headers=_csrf(client), json={
        "username": "globex_staff", "email": "g@globex.com", "password": PASSWORD, "role": "user",
        "client_id": accounts["globex"].id})
    assert ok.status_code == 201 and ok.json()["client_name"] == "globex"
    listed = client.get("/api/admin/users", params={"client_id": accounts["globex"].id}).json()
    assert [u["username"] for u in listed] == ["globex_staff"]
    # a client that still has users cannot be turned into another role
    assert client.patch(f"/api/admin/users/{accounts['acme'].id}", headers=_csrf(client),
                        json={"role": "admin"}).status_code == 400
    # a user cannot own a mailbox
    assert client.patch(f"/api/integrations/{accounts['box_acme'].id}", headers=_csrf(client),
                        json={"owner_user_id": accounts["staff"].id}).status_code == 422
