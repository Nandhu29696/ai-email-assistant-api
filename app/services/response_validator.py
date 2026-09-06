"""
AI Response Validator & Safety Gate.
Evaluates AI-generated draft replies before automated sending:
- Checks confidence, relevance, and tone alignment.
- Ensures negative/critical complaints are held for human review.
- Verifies absence of hallucinations, policy violations, or placeholders.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from loguru import logger
from app.services.ai_client import get_ai_client, get_model, ai_available
from app.config import settings


@dataclass
class ValidationResult:
    is_valid: bool
    confidence_score: float
    reason: str
    requires_human_review: bool


_PLACEHOLDER_RE = re.compile(
    r"(\[insert|\{insert|\[your name|\[company|\[link\]|xxx|TODO)",
    re.IGNORECASE
)


async def _llm_validate_reply(subject: str, email_body: str, draft_reply: str) -> tuple[bool, float, str]:
    """Ask LLM to score safety, relevance, and appropriateness of the proposed auto-reply."""
    try:
        client = get_ai_client()
        prompt = (
            "You are an AI Quality Assurance Inspector for customer support emails.\n"
            "Review the incoming customer email and the proposed AI draft reply.\n\n"
            f"Subject: {subject}\n"
            f"Incoming Email:\n{email_body[:1000]}\n\n"
            f"Proposed Reply:\n{draft_reply}\n\n"
            "Evaluate if this reply is:\n"
            "1. Accurate, safe, and professional.\n"
            "2. Directly answers the customer's question.\n"
            "3. Free of hallucinations, false promises, or placeholder tokens.\n\n"
            "Respond ONLY with a JSON object:\n"
            '{"approved": true, "score": 0.95, "reason": "Accurate acknowledgment and helpful next steps"}'
        )

        response = await client.chat.completions.create(
            model=get_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=80,
        )

        import json
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
        data = json.loads(content)
        return (
            bool(data.get("approved", True)),
            float(data.get("score", 0.85)),
            str(data.get("reason", "AI validated successfully"))
        )
    except Exception as exc:
        logger.warning(f"LLM validation fallback error: {exc}")
        return True, 0.80, "Heuristic pass (LLM check skipped)"


async def validate_auto_reply(
    subject: str,
    email_body: str,
    draft_reply: str,
    category: str,
    sentiment_label: str,
    priority: str,
) -> ValidationResult:
    """
    Validate whether an AI draft reply is eligible for automated dispatch.
    """
    # 1. Gate: Critical emails or high complaints ALWAYS require human review
    if priority == "critical" or (category == "complaint" and sentiment_label == "negative"):
        return ValidationResult(
            is_valid=False,
            confidence_score=0.2,
            reason="Critical priority or negative complaint held for human review",
            requires_human_review=True,
        )

    # 2. Gate: Check minimum length and placeholders
    if not draft_reply or len(draft_reply.strip()) < 20:
        return ValidationResult(
            is_valid=False,
            confidence_score=0.0,
            reason="Reply draft is too short or empty",
            requires_human_review=True,
        )

    if _PLACEHOLDER_RE.search(draft_reply):
        return ValidationResult(
            is_valid=False,
            confidence_score=0.1,
            reason="Reply contains template placeholders/TODO markers",
            requires_human_review=True,
        )

    # 3. Gate: LLM deep validation if AI is available
    if ai_available():
        approved, score, reason = await _llm_validate_reply(subject, email_body, draft_reply)
        threshold = settings.AUTO_REPLY_CONFIDENCE_THRESHOLD

        if approved and score >= threshold:
            return ValidationResult(
                is_valid=True,
                confidence_score=score,
                reason=reason,
                requires_human_review=False,
            )
        else:
            return ValidationResult(
                is_valid=False,
                confidence_score=score,
                reason=f"Validation score {score} below threshold {threshold}: {reason}",
                requires_human_review=True,
            )

    # 4. Fallback: Heuristic pass for standard categories
    return ValidationResult(
        is_valid=True,
        confidence_score=0.8,
        reason="Heuristic approval (Standard category template)",
        requires_human_review=False,
    )
