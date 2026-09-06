from app.schemas.email import (
    EmailBase, EmailCreate, EmailOut, EmailListOut,
    EmailUpdateRequest, AnalysisOut, IntegrationOut,
    NotificationOut, EmotionItem,
)
from app.schemas.dashboard import (
    DashboardStats, TrendsResponse, TrendPoint,
    SentimentBreakdown, PriorityBreakdown, CategoryBreakdown,
)

__all__ = [
    "EmailBase", "EmailCreate", "EmailOut", "EmailListOut",
    "EmailUpdateRequest", "AnalysisOut", "IntegrationOut",
    "NotificationOut", "EmotionItem",
    "DashboardStats", "TrendsResponse", "TrendPoint",
    "SentimentBreakdown", "PriorityBreakdown", "CategoryBreakdown",
]
