"""
Priority assignment based on sentiment, emotions, and category.
Returns: critical | high | medium | low
"""
from dataclasses import dataclass


# Priority score constants
PRIORITY_CRITICAL = 4
PRIORITY_HIGH = 3
PRIORITY_MEDIUM = 2
PRIORITY_LOW = 1

_SCORE_TO_LABEL = {
    4: "critical",
    3: "high",
    2: "medium",
    1: "low",
}

# Category base priority
_CATEGORY_BASE: dict[str, int] = {
    "complaint": PRIORITY_HIGH,
    "refund":    PRIORITY_HIGH,
    "support":   PRIORITY_MEDIUM,
    "invoice":   PRIORITY_MEDIUM,
    "feedback":  PRIORITY_LOW,
    "sales":     PRIORITY_LOW,
    "general":   PRIORITY_LOW,
}

# Emotion modifiers (additive)
_EMOTION_MODIFIER: dict[str, int] = {
    "anger":        2,
    "urgency":      2,
    "frustration":  1,
    "concern":      1,
    "satisfaction": -1,
    "excitement":   0,
    "neutral":      0,
}


@dataclass
class PriorityResult:
    priority: str       # critical | high | medium | low
    score: int          # 1–4


def assign_priority(
    sentiment_label: str,
    sentiment_score: float,
    primary_emotion: str,
    category: str,
) -> PriorityResult:
    """
    Compute email priority from ML signals.

    Scoring rules:
      Base score from category (1–3)
      + sentiment modifier (negative=+1, positive=-1)
      + emotion modifier
      Clamped to [1, 4]
    """
    base = _CATEGORY_BASE.get(category, PRIORITY_LOW)

    # Sentiment modifier
    if sentiment_label == "negative":
        sentiment_mod = 1
        if sentiment_score <= -0.5:   # strongly negative
            sentiment_mod = 2
    elif sentiment_label == "positive":
        sentiment_mod = -1
    else:
        sentiment_mod = 0

    # Emotion modifier
    emotion_mod = _EMOTION_MODIFIER.get(primary_emotion, 0)

    score = base + sentiment_mod + emotion_mod
    score = max(PRIORITY_LOW, min(PRIORITY_CRITICAL, score))   # clamp 1–4

    return PriorityResult(
        priority=_SCORE_TO_LABEL[score],
        score=score,
    )
