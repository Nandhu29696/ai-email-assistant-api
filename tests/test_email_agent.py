import asyncio
from datetime import datetime, timezone

from app.models.document_intake import EmailBatch
from app.services.email_agent import draft_reply


def test_agent_uses_safe_fallback_without_llm(monkeypatch):
    monkeypatch.setattr("app.services.email_agent.ai_available", lambda: False)
    batch = EmailBatch(
        batch_no="TEST-0001",
        message_id="message-1",
        sender_email="sender@example.com",
        subject="Documents",
        body_text="Please find the requested documents attached.",
        status="SUCCESS",
        outcome="PROCESSED",
        received_datetime=datetime.now(timezone.utc),
    )

    result = asyncio.run(draft_reply(batch, []))

    assert result.used_fallback is True
    assert result.action == "acknowledge"
    assert result.draft.startswith("Hello,")


def test_agent_rejects_invalid_model_output(monkeypatch):
    monkeypatch.setattr("app.services.email_agent.ai_available", lambda: True)
    monkeypatch.setattr("app.services.email_agent.get_model", lambda: "test-model")

    class FakeCompletions:
        async def create(self, **kwargs):
            class Message:
                content = '{"draft": "[Your Name]", "action": "send_money", "tone": "formal"}'

            class Choice:
                message = Message()

            class Response:
                choices = [Choice()]

            return Response()

    class FakeClient:
        class Chat:
            completions = FakeCompletions()

        chat = Chat()

    monkeypatch.setattr("app.services.email_agent.get_ai_client", lambda: FakeClient())
    batch = EmailBatch(
        batch_no="TEST-0002",
        message_id="message-2",
        sender_email="sender@example.com",
        status="FAILED",
        outcome="SYSTEM_ERROR",
        status_reason="Converter unavailable",
        received_datetime=datetime.now(timezone.utc),
    )

    result = asyncio.run(draft_reply(batch, []))

    assert result.used_fallback is True
    assert result.action == "escalate"