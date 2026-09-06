"""
Sentiment analysis using VADER (Valence Aware Dictionary and sEntiment Reasoner).
Fast, lexicon-based, no GPU needed — ideal for email text.
"""
from dataclasses import dataclass
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()


@dataclass
class SentimentResult:
    label: str          # positive | neutral | negative
    score: float        # compound score -1.0 … 1.0
    positive: float
    neutral: float
    negative: float


def analyze_sentiment(text: str) -> SentimentResult:
    """
    Analyse sentiment of the provided text.

    Thresholds (VADER recommended):
      compound >= 0.05  → positive
      compound <= -0.05 → negative
      otherwise         → neutral
    """
    if not text or not text.strip():
        return SentimentResult(
            label="neutral", score=0.0,
            positive=0.0, neutral=1.0, negative=0.0
        )

    scores = _analyzer.polarity_scores(text)
    compound = round(scores["compound"], 4)

    if compound >= 0.05:
        label = "positive"
    elif compound <= -0.05:
        label = "negative"
    else:
        label = "neutral"

    return SentimentResult(
        label=label,
        score=compound,
        positive=round(scores["pos"], 4),
        neutral=round(scores["neu"], 4),
        negative=round(scores["neg"], 4),
    )
