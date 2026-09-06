from pydantic import BaseModel
from typing import Any


class SentimentBreakdown(BaseModel):
    positive: int = 0
    neutral: int = 0
    negative: int = 0


class PriorityBreakdown(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class CategoryBreakdown(BaseModel):
    complaint: int = 0
    support: int = 0
    sales: int = 0
    refund: int = 0
    invoice: int = 0
    feedback: int = 0
    general: int = 0


class TrendPoint(BaseModel):
    date: str           # ISO date string
    positive: int = 0
    neutral: int = 0
    negative: int = 0
    total: int = 0


class DashboardStats(BaseModel):
    total_emails: int = 0
    unread_emails: int = 0
    processed_emails: int = 0
    critical_emails: int = 0
    avg_sentiment_score: float = 0.0
    sentiment: SentimentBreakdown = SentimentBreakdown()
    priority: PriorityBreakdown = PriorityBreakdown()
    category: CategoryBreakdown = CategoryBreakdown()


class TrendsResponse(BaseModel):
    trends: list[TrendPoint]
    period_days: int
