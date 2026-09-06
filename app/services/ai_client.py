"""
Shared AI client factory.
Returns an OpenAI-compatible AsyncOpenAI client pointing at
either Ollama (local) or OpenAI cloud, depending on config.
"""
from __future__ import annotations
from openai import AsyncOpenAI
from app.config import settings


def get_ai_client() -> AsyncOpenAI:
    """Return an AsyncOpenAI client configured for the active backend."""
    if settings.OLLAMA_BASE_URL:
        return AsyncOpenAI(
            base_url=f"{settings.OLLAMA_BASE_URL.rstrip('/')}/v1",
            api_key="ollama",          # Ollama ignores the key
        )
    return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


def get_model() -> str:
    """Return the active model name."""
    if settings.OLLAMA_BASE_URL:
        return settings.OLLAMA_MODEL
    return settings.OPENAI_MODEL


def ai_available() -> bool:
    """True when at least one AI backend is configured."""
    return bool(settings.OLLAMA_BASE_URL or settings.OPENAI_API_KEY)
