"""
AI email summarization – uses Ollama (or OpenAI as fallback).
Falls back to extractive summarization when no AI backend is configured.
"""
from __future__ import annotations
import re

from loguru import logger

from app.observability import LLM_CALLS
from app.services.ai_client import get_ai_client, get_model, ai_available, fence_untrusted, UNTRUSTED_NOTE, strip_preamble, is_refusal


async def _openai_summarize(subject: str, body: str, thread_context: list[str] | None = None) -> str:
    client = get_ai_client()

    thread_snippet = ""
    if thread_context:
        thread_snippet = "\n\nPrevious Thread Context:\n" + fence_untrusted("\n---\n".join(thread_context[-3:]), 1500)

    prompt = (
        "Summarize the following email in 2-3 concise sentences. "
        "Focus on the main point, the sender's request or concern, and any expected action.\n"
        f"{UNTRUSTED_NOTE}\n\n"
        f"Subject: {fence_untrusted(subject, 300)}\n\n"
        f"Body:\n{fence_untrusted(body, 2000)}"
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


# Short emails are their own summary; asking the model only invites odd answers.
SHORT_EMAIL_WORDS = 30

# The model sometimes describes the prompt instead of the email ("There is no email content...").
_META_RE = re.compile(
    r"\b(no (actual )?email (content|body|text)|placeholder|untrusted[_ ]email[_ ]content|"
    r"(treat|treated) (it )?(strictly )?as data|as an ai\b)",
    re.IGNORECASE,
)


def _short_summary(subject: str, body: str) -> str:
    text = " ".join(body.split())
    if not text:
        return subject or "(empty email)"
    return text if len(text) <= 300 else text[:297].rstrip() + "..."


async def generate_summary(subject: str, body: str, thread_context: list[str] | None = None) -> str:
    """
    Generate a concise summary of the email.
    Short emails are returned as-is; otherwise the LLM is used, falling back to
    an extractive summary when it is unavailable or answers off-topic.
    """
    if not body or not body.strip():
        return subject or "(empty email)"
    if len(body.split()) < SHORT_EMAIL_WORDS:
        return _short_summary(subject, body)

    if ai_available():
        try:
            summary = strip_preamble(await _openai_summarize(subject, body, thread_context=thread_context))
            LLM_CALLS.labels("summarize", "success").inc()
            if summary and not is_refusal(summary) and not _META_RE.search(summary):
                return summary
            logger.info("[summarizer] LLM declined or returned nothing; using extractive summary")
        except Exception as exc:
            LLM_CALLS.labels("summarize", "error").inc()
            logger.warning(f"[summarizer] LLM summary failed, using extractive summary: {exc}")

    return _extractive_summarize(body)
