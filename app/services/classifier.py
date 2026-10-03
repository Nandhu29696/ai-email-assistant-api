"""
Email category classifier.
Uses keyword/pattern matching as primary method,
with OpenAI as fallback for ambiguous cases.
"""
from __future__ import annotations
import re

from loguru import logger
from dataclasses import dataclass
from app.services.ai_client import (
    get_ai_client, get_model, ai_available, fence_untrusted, UNTRUSTED_NOTE, parse_json_response,
)

from app.observability import LLM_CALLS

VALID_CATEGORIES = ("complaint", "support", "sales", "refund", "invoice", "feedback", "general")

# ── Category keyword map ──────────────────────────────────────
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "complaint": [
        r"\bcompla(in|int)\b", r"\bunacceptable\b", r"\bscam\b",
        r"\bterrible service\b", r"\bworse (experience|service)\b",
        r"\bwant (a refund|my money back)\b", r"\bvery disappointed\b",
        r"\breport (you|this)\b", r"\blawyer\b", r"\bbbb\b",
    ],
    "refund": [
        r"\brefund\b", r"\bchargeback\b", r"\bmoney back\b",
        r"\bcancel(led|ation)?\b", r"\bover(charged|billed)\b",
        r"\bduplicate (charge|payment)\b", r"\btransaction reversed\b",
    ],
    "invoice": [
        r"\binvoice\b", r"\bbilling\b", r"\bstatement\b", r"\breceipt\b",
        r"\bpayment due\b", r"\bamount owed\b", r"\bpurchase order\b",
        r"\bpo number\b", r"\bnet [0-9]+\b",
    ],
    "support": [
        r"\bhelp\b", r"\bnot working\b", r"\berror\b", r"\bbug\b",
        r"\bcan't (login|sign in|access)\b", r"\bpassword reset\b",
        r"\btechnical (issue|problem|support)\b", r"\bbroken\b",
        r"\bhow (do|can) I\b", r"\bsteps to\b",
    ],
    "sales": [
        r"\bpric(e|ing)\b", r"\bquot(e|ation)\b", r"\bpartnership\b",
        r"\bcollaboration\b", r"\bbulk (order|discount)\b", r"\bpurchase\b",
        r"\bsubscri(be|ption)\b", r"\bupgrade\b", r"\benterprise plan\b",
        r"\bdemo\b", r"\btrial\b",
    ],
    "feedback": [
        r"\bfeedback\b", r"\bsuggestion\b", r"\bfeature request\b",
        r"\bimprovement\b", r"\bwould (love|like) to see\b",
        r"\brated\b", r"\breview\b", r"\bsurvey\b",
    ],
}

_COMPILED: dict[str, list[re.Pattern]] = {
    cat: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cat, patterns in _CATEGORY_KEYWORDS.items()
}

_NEGATION_RE = re.compile(r"\b(don't|do not|no|not|never|without)\b\s+\w+\s+\b(refund|complaint|problem|issue|error)\b", re.IGNORECASE)


@dataclass
class ClassificationResult:
    category: str
    confidence: float


def _keyword_classify(text: str) -> ClassificationResult | None:
    scores: dict[str, int] = {}
    has_negation = bool(_NEGATION_RE.search(text))

    for category, patterns in _COMPILED.items():
        score = sum(1 for p in patterns if p.search(text))
        if score:
            # If negation pattern detected and matches complaint/refund/support, lower confidence
            if has_negation and category in ("complaint", "refund", "support"):
                score = max(1, score - 1)
            scores[category] = score

    if not scores:
        return None

    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = round(scores[best] / total, 3) if total else 0.0
    if has_negation:
        confidence = max(0.2, confidence - 0.2)
    return ClassificationResult(category=best, confidence=confidence)


async def _openai_classify(text: str) -> ClassificationResult:
    """Use local LLM (Ollama) or OpenAI as fallback for ambiguous emails."""
    try:
        client = get_ai_client()

        prompt = (
            "Classify the following email into exactly ONE of these categories:\n"
            "complaint, support, sales, refund, invoice, feedback, general\n\n"
            "Respond with ONLY a JSON object like: {\"category\": \"support\", \"confidence\": 0.9}\n\n"
            f"{UNTRUSTED_NOTE}\n\nEmail:\n{fence_untrusted(text, 1500)}"
        )

        response = await client.chat.completions.create(
            model=get_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=60,
        )

        data = parse_json_response(response.choices[0].message.content)
        category = str(data.get("category", "general")).strip().lower()
        if category not in VALID_CATEGORIES:
            category = "general"
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0.5))))
        LLM_CALLS.labels("classify", "success").inc()
        return ClassificationResult(category=category, confidence=round(confidence, 3))
    except Exception as exc:
        LLM_CALLS.labels("classify", "error").inc()
        logger.warning(f"[classifier] LLM classification failed, using 'general': {exc}")
        return ClassificationResult(category="general", confidence=0.3)


async def classify_email(text: str) -> ClassificationResult:
    """
    Classify email category.
    Uses keyword matching; falls back to LLM for low-confidence cases.
    """
    if not text or not text.strip():
        return ClassificationResult(category="general", confidence=0.0)

    result = _keyword_classify(text)

    # Use LLM (Ollama / OpenAI) if no keywords matched or confidence is low
    if result is None or result.confidence < 0.45:
        if ai_available():
            return await _openai_classify(text)
        return result or ClassificationResult(category="general", confidence=0.3)

    return result
