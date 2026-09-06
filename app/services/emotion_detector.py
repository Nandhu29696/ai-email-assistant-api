"""
Emotion detection using keyword/pattern heuristics + optional transformer model.
Returns a ranked list of detected emotions with confidence scores.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field

# ── Keyword maps ──────────────────────────────────────────────
_EMOTION_KEYWORDS: dict[str, list[str]] = {
    "anger": [
        r"\bunacceptable\b", r"\boutrageous\b", r"\bfurious\b", r"\bangry\b",
        r"\brage\b", r"\binfuriated\b", r"\bappalled\b", r"\bdisgrace\b",
        r"\bnever again\b", r"\bdemand\b", r"\bthis is ridiculous\b",
    ],
    "frustration": [
        r"\bfrustrat(ed|ing|ion)\b", r"\bannoy(ed|ing)\b", r"\bdisappoint(ed|ing)\b",
        r"\bfed up\b", r"\bstill (waiting|haven't)\b", r"\bno response\b",
        r"\bkeep (calling|trying|waiting)\b", r"\bover and over\b",
        r"\bwhy (hasn't|haven't|don't you)\b",
    ],
    "urgency": [
        r"\burgent\b", r"\basap\b", r"\bas soon as possible\b",
        r"\bimmediately\b", r"\bright away\b", r"\bdeadline\b",
        r"\btime.sensitive\b", r"\bcritical\b", r"\bemergency\b",
        r"\bpriority\b", r"\btoday\b", r"\bby (end of day|eod|cob)\b",
    ],
    "concern": [
        r"\bconcern(ed|ing)?\b", r"\bworr(ied|ying|y)\b", r"\bissue\b",
        r"\bproblem\b", r"\berror\b", r"\bnot working\b", r"\bbroken\b",
        r"\bstill (broken|not fixed|failing)\b", r"\bconfus(ed|ing)\b",
    ],
    "satisfaction": [
        r"\bthank\b", r"\bgreat\b", r"\bexcellent\b", r"\bamazing\b",
        r"\bwonderful\b", r"\bhappy\b", r"\bperfect\b", r"\blove it\b",
        r"\bappreciat(e|ed)\b", r"\bimpressed\b", r"\bfantastic\b",
        r"\bjust what I needed\b", r"\bkept your promise\b",
    ],
    "excitement": [
        r"\bexcit(ed|ing)\b", r"\bcan't wait\b", r"\blooking forward\b",
        r"\bthrill(ed|ing)\b", r"\bdelighted\b", r"\bso happy\b",
        r"\bincredible\b", r"\bcan't believe\b",
    ],
}

# Pre-compile patterns
_COMPILED: dict[str, list[re.Pattern]] = {
    emotion: [re.compile(p, re.IGNORECASE) for p in patterns]
    for emotion, patterns in _EMOTION_KEYWORDS.items()
}


@dataclass
class EmotionScore:
    emotion: str
    score: float


@dataclass
class EmotionResult:
    primary_emotion: str
    emotions: list[EmotionScore] = field(default_factory=list)


def detect_emotions(text: str) -> EmotionResult:
    """
    Detect emotions from email text using keyword matching.
    Returns a ranked list; primary_emotion is the highest-scoring one.
    """
    if not text or not text.strip():
        return EmotionResult(primary_emotion="neutral", emotions=[])

    word_count = max(len(text.split()), 1)
    raw_scores: dict[str, float] = {}

    for emotion, patterns in _COMPILED.items():
        matches = sum(1 for p in patterns if p.search(text))
        if matches:
            # Normalize by doc length to avoid bias toward long emails
            raw_scores[emotion] = round(min(matches / (word_count / 50), 1.0), 3)

    if not raw_scores:
        return EmotionResult(primary_emotion="neutral", emotions=[])

    # Sort by score descending
    ranked = sorted(
        [EmotionScore(emotion=k, score=v) for k, v in raw_scores.items()],
        key=lambda x: x.score,
        reverse=True,
    )

    return EmotionResult(
        primary_emotion=ranked[0].emotion,
        emotions=ranked,
    )
