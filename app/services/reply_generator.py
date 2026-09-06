"""
AI-powered reply generator – uses Ollama (or OpenAI as fallback).
Generates professional, context-aware email replies.
"""
from __future__ import annotations
import re

from app.services.ai_client import get_ai_client, get_model, ai_available


_TONE_MAP = {
    "complaint": "empathetic and apologetic",
    "refund":    "empathetic and solution-focused",
    "support":   "helpful and technical",
    "invoice":   "professional and formal",
    "sales":     "enthusiastic and professional",
    "feedback":  "grateful and encouraging",
    "general":   "professional and friendly",
}


async def _openai_reply(
    subject: str,
    body: str,
    category: str,
    sentiment: str,
    thread_context: list[str] | None = None,
) -> str:
    client = get_ai_client()

    tone = _TONE_MAP.get(category, "professional and friendly")
    urgency_note = (
        "The sender seems upset or urgent — prioritize acknowledgment."
        if sentiment == "negative" else ""
    )

    thread_snippet = ""
    if thread_context:
        thread_snippet = "\n\nPrevious Conversation History in this Thread:\n" + "\n---\n".join(thread_context[-3:])

    prompt = (
        f"You are a professional customer service representative. "
        f"Write a helpful, {tone} reply to the following email. "
        f"{urgency_note}\n"
        "Keep it concise (3-5 sentences). Do not include a subject line.\n\n"
        f"Original Subject: {subject}\n\n"
        f"Original Email:\n{body[:1500]}"
        f"{thread_snippet}"
    )

    response = await client.chat.completions.create(
        model=get_model(),
        messages=[
            {
                "role": "system",
                "content": "You write professional, empathetic, and concise business email replies.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        max_tokens=300,
    )
    return response.choices[0].message.content.strip()


_TEMPLATE_REPLIES: dict[str, str] = {
    "complaint": (
        "Thank you for reaching out and bringing this to our attention. "
        "We sincerely apologize for the inconvenience you've experienced. "
        "Our team is looking into this matter and we will get back to you within 24 hours with a resolution. "
        "We value your business and are committed to making this right."
    ),
    "support": (
        "Thank you for contacting our support team. "
        "We've received your request and our team is working on it. "
        "Please expect a detailed response within 1-2 business days. "
        "If this is urgent, please reply with 'URGENT' and we will prioritize accordingly."
    ),
    "refund": (
        "Thank you for reaching out regarding your refund request. "
        "We have received your request and our finance team will process it within 3-5 business days. "
        "You will receive a confirmation email once the refund has been issued."
    ),
    "invoice": (
        "Thank you for your inquiry regarding the invoice. "
        "Our billing team has been notified and will review your request shortly. "
        "Please allow 1-2 business days for a response."
    ),
    "sales": (
        "Thank you for your interest in our products/services! "
        "We'd love to discuss how we can help you. "
        "A member of our sales team will be in touch within 24 hours to schedule a call."
    ),
    "feedback": (
        "Thank you so much for taking the time to share your feedback with us. "
        "Your insights are incredibly valuable and help us improve. "
        "We truly appreciate your continued support!"
    ),
    "general": (
        "Thank you for your email. "
        "We have received your message and will respond within 1-2 business days. "
        "If your matter is urgent, please call our support line."
    ),
}

_PLACEHOLDER_RE = re.compile(
    r"(\[insert|\{insert|\[your name|\[company|\[link\]|xxx|TODO)",
    re.IGNORECASE,
)


async def generate_reply(
    subject: str,
    body: str,
    category: str,
    sentiment: str,
    thread_context: list[str] | None = None,
) -> str:
    """
    Generate a professional reply suggestion.
    Uses LLM (Ollama/OpenAI) if available; falls back to category templates.
    """
    if ai_available():
        try:
            generated = await _openai_reply(subject, body, category, sentiment, thread_context=thread_context)
            if generated and len(generated.strip()) >= 20 and not _PLACEHOLDER_RE.search(generated):
                return generated
        except Exception:
            pass

    return _TEMPLATE_REPLIES.get(category, _TEMPLATE_REPLIES["general"])
