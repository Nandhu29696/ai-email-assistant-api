"""Tests for the schema-sync script, LLM health check and LLM fallback logging."""
import asyncio

import pytest
from loguru import logger
from sqlalchemy import create_engine, inspect, text

from app.database import Base
import app.models  # noqa: F401


# ── LLM health check ──────────────────────────────────────────
def test_llm_health_requires_configured_model():
    from app.main import llm_model_status

    assert llm_model_status(200, {"models": []}, "llama3.2", "ollama") == (
        False, "model 'llama3.2' is not available on the ollama server",
    )
    assert llm_model_status(200, {"models": [{"name": "llama3.2:latest"}]}, "llama3.2", "ollama")[0] is True
    assert llm_model_status(200, {"models": [{"name": "mistral:7b"}]}, "mistral:7b", "ollama")[0] is True
    assert llm_model_status(200, {"data": [{"id": "gpt-4o-mini"}]}, "gpt-4o-mini", "openai")[0] is True
    assert llm_model_status(401, None, "gpt-4o-mini", "openai") == (False, "HTTP 401")


# ── LLM fallbacks are visible ─────────────────────────────────
@pytest.fixture()
def captured_logs():
    messages = []
    sink = logger.add(lambda m: messages.append(m.record["message"]), level="WARNING")
    yield messages
    logger.remove(sink)


class _FailingClient:
    class chat:  # noqa: N801
        class completions:  # noqa: N801
            @staticmethod
            async def create(**_kwargs):
                raise RuntimeError("model 'llama3.2' not found")


def test_llm_failures_are_logged_not_silent(monkeypatch, captured_logs):
    from app.services import classifier

    monkeypatch.setattr(classifier, "get_ai_client", lambda: _FailingClient())
    monkeypatch.setattr(classifier, "ai_available", lambda: True)

    result = asyncio.run(classifier._openai_classify("hello"))

    assert result.category == "general"   # graceful fallback still works
    joined = " | ".join(captured_logs)
    assert "[classifier]" in joined and "llama3.2" in joined


# ── Schema sync script ────────────────────────────────────────
@pytest.fixture()
def legacy_db(tmp_path, monkeypatch):
    """A SQLite database at the current schema minus some columns/tables, without alembic_version."""
    from scripts import sync_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN mfa_enabled"))
        conn.execute(text("DROP INDEX ix_email_batches_outcome"))
        conn.execute(text("ALTER TABLE email_batches DROP COLUMN outcome"))
        conn.execute(text("ALTER TABLE email_integrations DROP COLUMN process_since"))
        conn.execute(text("DROP TABLE failed_jobs"))
        conn.execute(text(
            "INSERT INTO users (email, username, hashed_password, role, is_active) "
            "VALUES ('legacy@example.com', 'legacy', 'h', 'employee', 1)"
        ))
        conn.execute(text("INSERT INTO email_integrations (provider, email_address, is_active) VALUES ('gmail', 'box@example.com', 1)"))
        conn.execute(text(
            "INSERT INTO user_sessions (user_id, refresh_token, is_active, expires_at) "
            "VALUES (1, 'plain-text-legacy-token', 1, '2099-01-01 00:00:00')"
        ))
    monkeypatch.setattr(sync_schema, "engine", engine)
    yield engine, sync_schema, tmp_path
    engine.dispose()


def test_sync_schema_dry_run_changes_nothing(legacy_db, capsys):
    engine, sync_schema, tmp_path = legacy_db
    assert sync_schema.sync(apply=False) == 0
    out = capsys.readouterr().out
    assert "add column users.mfa_enabled" in out and "create table failed_jobs" in out
    assert "mfa_enabled" not in {c["name"] for c in inspect(engine).get_columns("users")}


def test_sync_schema_apply_is_complete_and_idempotent(legacy_db, capsys):
    engine, sync_schema, tmp_path = legacy_db
    assert sync_schema.sync(apply=True, backup_dir=str(tmp_path / "backups")) == 0
    insp = inspect(engine)
    assert "mfa_enabled" in {c["name"] for c in insp.get_columns("users")}
    assert "outcome" in {c["name"] for c in insp.get_columns("email_batches")}
    assert insp.has_table("failed_jobs")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT role FROM users")).scalar() == "client"
        assert conn.execute(text("SELECT is_active FROM user_sessions")).scalar() in (0, False)
        # existing mailboxes start from "now": their old backlog is not auto-replied
        assert conn.execute(text("SELECT process_since FROM email_integrations")).scalar() is not None
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == sync_schema._alembic_head()
    assert list((tmp_path / "backups").glob("before_*.json")), "rollback snapshot written"

    capsys.readouterr()
    assert sync_schema.sync(apply=False) == 0
    assert "0 change(s) planned" in capsys.readouterr().out


# ── LLM limiter and output clean-up ───────────────────────────
def test_llm_calls_are_serialised_for_ollama(monkeypatch):
    from app.services import ai_client

    monkeypatch.setattr(ai_client.settings, "OLLAMA_BASE_URL", "http://ollama.test")
    monkeypatch.setattr(ai_client.settings, "LLM_MAX_CONCURRENCY", 0)
    active, peak = 0, 0

    class FakeCompletions:
        async def create(self, **_):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return "ok"

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    async def scenario():
        client = ai_client.LimitedClient(FakeClient(), ai_client._max_concurrency())
        return await asyncio.gather(*(client.chat.completions.create(model="m") for _ in range(4)))

    assert asyncio.run(scenario()) == ["ok"] * 4
    assert peak == 1


def test_reply_and_summary_cleanup():
    from app.services.ai_client import clean_reply, strip_preamble

    assert strip_preamble("Here is a summary of the email:\n\nCustomer was charged twice.") == "Customer was charged twice."
    assert strip_preamble("Customer asks about hours.") == "Customer asks about hours."
    cleaned = clean_reply("Subject: Re: Hours\n\nHi,\n\nWe open at 9.\n\nBest regards,\n[Your Name]\n[Company Name]")
    assert cleaned == "Hi,\n\nWe open at 9.\n\nBest regards,"
    # Placeholders inside the text are not silently removed (the reply is still rejected upstream).
    assert "[insert link]" in clean_reply("Please visit [insert link] for details.")


def test_greeting_placeholder_and_generic_placeholders():
    from app.services.ai_client import PLACEHOLDER_RE, clean_reply

    assert clean_reply("Dear [Name],\n\nThanks for reaching out.") == "Hello,\n\nThanks for reaching out."
    assert PLACEHOLDER_RE.search("Hi there, contact [Support Email] for help")
    assert PLACEHOLDER_RE.search("Regards, {{agent_name}}")
    assert not PLACEHOLDER_RE.search("See [our guide](https://example.com/guide)")


def test_model_refusals_are_detected():
    from app.services import ai_client

    assert ai_client.is_refusal("I can't fulfill this request.")
    assert ai_client.is_refusal("I'm sorry, but I cannot help with that.")
    assert not ai_client.is_refusal("The customer cannot log in to the portal.")
