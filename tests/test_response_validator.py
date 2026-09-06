import asyncio
import pytest
from app.services.response_validator import validate_auto_reply, ValidationResult


def test_validate_auto_reply_rejects_critical_complaints():
    res = asyncio.run(validate_auto_reply(
        subject="I am furious with your service",
        email_body="This is broken and I demand immediate compensation!",
        draft_reply="Dear customer, we are very sorry and will fix this right away.",
        category="complaint",
        sentiment_label="negative",
        priority="critical",
    ))
    assert res.is_valid is False
    assert res.requires_human_review is True
    assert "held for human review" in res.reason.lower()


def test_validate_auto_reply_rejects_placeholders():
    res = asyncio.run(validate_auto_reply(
        subject="Invoice inquiry",
        email_body="Can you send my invoice?",
        draft_reply="Hello, please check your invoice at [insert link here]. Best, [Company Name]",
        category="invoice",
        sentiment_label="neutral",
        priority="medium",
    ))
    assert res.is_valid is False
    assert res.requires_human_review is True
    assert "placeholder" in res.reason.lower()


def test_validate_auto_reply_approves_standard_safe_replies():
    res = asyncio.run(validate_auto_reply(
        subject="General Question regarding hours",
        email_body="Hello, what are your customer support working hours during the week?",
        draft_reply="Thank you for reaching out. Our support team is available Monday through Friday from 9 AM to 6 PM EST. Please let us know if we can assist you with anything else.",
        category="general",
        sentiment_label="neutral",
        priority="low",
    ))
    assert res.is_valid is True
    assert res.requires_human_review is False
    assert res.confidence_score >= 0.70
