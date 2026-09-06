"""
AI email summarization – uses Ollama (or OpenAI as fallback).
Falls back to extractive summarization when no AI backend is configured.
"""
from __future__ import annotations
import re
from app.services.ai_client import get_ai_client, get_model, ai_available


async def _openai_summarize(subject: str, body: str, thread_context: list[str] | None = None) -> str:
    client = get_ai_client()

    thread_snippet = ""
    if thread_context:
        thread_snippet = "\n\nPrevious Thread Context:\n" + "\n---\n".join(thread_context[-3:])

    prompt = (
        "Summarize the following email in 2-3 concise sentences. "
        "Focus on the main point, the sender's request or concern, and any expected action.\n\n"
        f"Subject: {subject}\n\n"
        f"Body:\n{body[:2000]}"
        f"{thread_snippet}"
    )

    response = await client.chat.completions.create(
        model=get_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=150,
    )
    return response.choices[0].message.content.strip()


def _extractive_summarize(body: str, max_sentences: int = 3) -> str:
    """Simple extractive summarizer — returns first N meaningful sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", body)
    meaningful = [s.strip() for s in sentences if len(s.split()) > 5]
    return " ".join(meaningful[:max_sentences]) or body[:300]


async def generate_summary(subject: str, body: str, thread_context: list[str] | None = None) -> str:
    """
    Generate a concise summary of the email.
    Uses LLM if available; otherwise extractive fallback.
    """
    if not body or not body.strip():
        return subject or "(empty email)"

    if ai_available():
        try:
            return await _openai_summarize(subject, body, thread_context=thread_context)
        except Exception:
            pass  # fall through to extractive

    return _extractive_summarize(body)
