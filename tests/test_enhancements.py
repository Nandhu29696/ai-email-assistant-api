"""Tests for cookies/CSRF, MFA, the dead-letter queue and per-mailbox policies."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.email import EmailIntegration
from app.models.user import FailedJob, User
from app.routers.auth import hash_password
from app.services import mfa


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


def _login(client, username, password="Sup3rSecret99"):
    response = client.post("/api/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def _csrf(client) -> dict:
    return {"X-CSRF-Token": client.cookies.get("ea_csrf")}


# ── httpOnly cookies + CSRF ───────────────────────────────────
def test_login_sets_httponly_cookies_and_hides_tokens(client, db_session):
    _user(db_session, "cookie")
    response = _login(client, "cookie")
    body = response.json()
    assert "access_token" not in body and "refresh_token" not in body
    set_cookie = " ".join(response.headers.get_list("set-cookie")).lower()
    assert "ea_access=" in set_cookie and "httponly" in set_cookie
    assert client.get("/api/auth/me").status_code == 200  # authenticated by cookie


def test_cookie_auth_requires_csrf_for_writes(client, db_session):
    _user(db_session, "csrf")
    _login(client, "csrf")
    payload = {"current_password": "wrong", "new_password": "An0therPassword"}
    assert client.post("/api/auth/change-password", json=payload).status_code == 403
    assert client.post("/api/auth/change-password", json=payload, headers=_csrf(client)).status_code == 400


def test_cookie_refresh_and_logout(client, db_session):
    _user(db_session, "rotate")
    _login(client, "rotate")
    old_refresh = client.cookies.get("ea_refresh", path="/api/auth")
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert client.cookies.get("ea_refresh", path="/api/auth") != old_refresh
    assert client.post("/api/auth/logout", headers=_csrf(client)).status_code == 200
    assert client.get("/api/auth/me").status_code == 401


# ── MFA ───────────────────────────────────────────────────────
def test_totp_roundtrip_and_replay_protection():
    secret = mfa.generate_secret()
    step = mfa.current_step()
    code = mfa.totp(secret, step)
    assert mfa.verify_totp(secret, code) == step
    assert mfa.verify_totp(secret, code, last_used_step=step) is None   # replay rejected
    assert mfa.verify_totp(secret, "000000" if code != "000000" else "111111") is None


def test_mfa_enrollment_and_two_step_login(client, db_session):
    _user(db_session, "mfauser")
    _login(client, "mfauser")
    setup = client.post("/api/auth/mfa/setup", headers=_csrf(client)).json()
    assert setup["otpauth_uri"].startswith("otpauth://totp/")
    enabled = client.post("/api/auth/mfa/enable", json={"code": mfa.totp(setup["secret"])}, headers=_csrf(client))
    assert enabled.status_code == 200 and len(enabled.json()["recovery_codes"]) == 10
    recovery = enabled.json()["recovery_codes"][0]
    client.post("/api/auth/logout", headers=_csrf(client))

    first = client.post("/api/auth/login", data={"username": "mfauser", "password": "Sup3rSecret99"}).json()
    assert first["mfa_required"] is True and "ea_access" not in client.cookies
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": first["mfa_token"], "code": "123456"}).status_code == 401
    ok = client.post("/api/auth/mfa/verify", json={"mfa_token": first["mfa_token"], "code": recovery})
    assert ok.status_code == 200 and client.get("/api/auth/me").json()["mfa_enabled"] is True
    # Recovery codes are single-use.
    second = client.post("/api/auth/login", data={"username": "mfauser", "password": "Sup3rSecret99"}).json()
    assert client.post("/api/auth/mfa/verify", json={"mfa_token": second["mfa_token"], "code": recovery}).status_code == 401


# ── Per-user notifications ────────────────────────────────────
# ── Review queue ──────────────────────────────────────────────
# ── Dead-letter queue ─────────────────────────────────────────
def test_job_exhausting_retries_is_dead_lettered(db_session, monkeypatch):
    from arq import Retry
    from app.jobs import queue

    monkeypatch.setattr(queue, "record_dead_letter",
                        lambda name, args, key, attempts, err: db_session.add(
                            FailedJob(job_name=name, args_json=list(args), job_key=key, attempts=attempts, error=str(err))))

    @queue.job("always_fails_test", max_tries=2)
    async def always_fails(x):
        raise RuntimeError("boom")

    runner = queue.REGISTRY["always_fails_test"]
    with pytest.raises(Retry):
        asyncio.run(runner({"job_try": 1, "job_id": "k1"}, 7))
    assert asyncio.run(runner({"job_try": 2, "job_id": "k1"}, 7)) is None
    db_session.commit()
    row = db_session.query(FailedJob).filter(FailedJob.job_name == "always_fails_test").one()
    assert row.args_json == [7] and row.attempts == 2 and "boom" in row.error


def test_inline_queue_runs_job_when_redis_is_unavailable():
    from app.jobs import queue

    calls = []

    @queue.job("inline_probe_test")
    async def probe(value):
        await asyncio.sleep(0.3)  # still running when the duplicate is enqueued
        calls.append(value)

    async def scenario():
        status = await queue.enqueue("inline_probe_test", 42, job_id="probe-1")
        assert status == "inline"
        assert await queue.enqueue("inline_probe_test", 42, job_id="probe-1") == "duplicate"
        await asyncio.gather(*queue._inline_tasks)

    asyncio.run(scenario())
    assert calls == [42]


# ── Per-mailbox policies ──────────────────────────────────────
def test_per_mailbox_domain_allow_list(db_session):
    from app.services.document_intake.domain_validator import validate_domain

    class Mailbox:
        allowed_sender_domains = "partner.com"

    assert validate_domain(db_session, "a@partner.com", Mailbox()).is_allowed
    assert validate_domain(db_session, "a@mail.partner.com", Mailbox()).is_allowed   # subdomain
    assert not validate_domain(db_session, "a@evil.com", Mailbox()).is_allowed


def test_sender_authentication_failure_detection():
    from app.services.document_intake.sender_checks import sender_authentication_failed

    assert sender_authentication_failed({"Authentication-Results": "mx.google.com; dmarc=fail (p=REJECT)"})
    assert sender_authentication_failed({"Authentication-Results": "spf=fail smtp.mailfrom=x.com; dkim=none"})
    assert not sender_authentication_failed({"Authentication-Results": "spf=pass; dkim=pass; dmarc=pass"})
    assert not sender_authentication_failed({})


def test_integration_settings_validate_policies(client, db_session):
    owner = _user(db_session, "owner4")
    box = EmailIntegration(provider="gmail", email_address="box4@example.com", owner_user_id=owner.id)
    db_session.add(box)
    db_session.commit()
    _login(client, "owner4")
    bad = client.patch(f"/api/integrations/{box.id}", headers=_csrf(client),
                       json={"allowed_extensions": "pdf,exe"})
    assert bad.status_code == 422
    good = client.patch(f"/api/integrations/{box.id}", headers=_csrf(client), json={
        "allowed_sender_domains": "@Partner.com, other.org",
        "allowed_extensions": ".PDF, docx",
        "max_file_size_mb": 10,
    })
    assert good.status_code == 200, good.text
    db_session.refresh(box)
    assert box.allowed_sender_domains == "partner.com,other.org"
    assert box.allowed_extensions == "pdf,docx" and box.max_file_size_mb == 10
