"""
Dashboard router — statistics, trends, and category breakdowns.
"""
from __future__ import annotations
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case

from app.database import get_db
from app.models.email import Email, EmailAnalysis, EmailIntegration
from app.routers.auth import get_current_user
from app.models.user import User
from app.schemas.dashboard import (
    DashboardStats, TrendsResponse, TrendPoint,
    SentimentBreakdown, PriorityBreakdown, CategoryBreakdown,
)

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
def get_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Return aggregate dashboard statistics."""
    owner_id = None if current_user.role == "admin" else current_user.id

    email_query = db.query(
        func.count(Email.id),
        func.sum(case((Email.is_read == False, 1), else_=0)),
        func.sum(case((Email.processed_at.isnot(None), 1), else_=0)),
    ).join(EmailIntegration, Email.integration_id == EmailIntegration.id)
    if owner_id is not None:
        email_query = email_query.filter(EmailIntegration.owner_user_id == owner_id)
    total, unread, processed = email_query.one()

    analysis_query = db.query(
        func.sum(case((EmailAnalysis.sentiment == "positive", 1), else_=0)),
        func.sum(case((EmailAnalysis.sentiment == "neutral", 1), else_=0)),
        func.sum(case((EmailAnalysis.sentiment == "negative", 1), else_=0)),
        func.sum(case((EmailAnalysis.priority == "critical", 1), else_=0)),
        func.sum(case((EmailAnalysis.priority == "high", 1), else_=0)),
        func.sum(case((EmailAnalysis.priority == "medium", 1), else_=0)),
        func.sum(case((EmailAnalysis.priority == "low", 1), else_=0)),
        func.sum(case((EmailAnalysis.category == "complaint", 1), else_=0)),
        func.sum(case((EmailAnalysis.category == "support", 1), else_=0)),
        func.sum(case((EmailAnalysis.category == "sales", 1), else_=0)),
        func.sum(case((EmailAnalysis.category == "refund", 1), else_=0)),
        func.sum(case((EmailAnalysis.category == "invoice", 1), else_=0)),
        func.sum(case((EmailAnalysis.category == "feedback", 1), else_=0)),
        func.sum(case((EmailAnalysis.category == "general", 1), else_=0)),
        func.avg(EmailAnalysis.sentiment_score),
    ).join(Email, Email.id == EmailAnalysis.email_id).join(
        EmailIntegration, Email.integration_id == EmailIntegration.id
    )
    if owner_id is not None:
        analysis_query = analysis_query.filter(EmailIntegration.owner_user_id == owner_id)
    (
        positive, neutral, negative,
        critical, high, medium, low,
        complaint, support, sales, refund, invoice, feedback, general,
        avg_score,
    ) = analysis_query.one()

    total = total or 0
    unread = unread or 0
    processed = processed or 0
    avg_score = avg_score or 0.0

    return DashboardStats(
        total_emails=total,
        unread_emails=unread,
        processed_emails=processed,
        critical_emails=critical or 0,
        avg_sentiment_score=round(float(avg_score), 4),
        sentiment=SentimentBreakdown(
            positive=positive or 0, neutral=neutral or 0, negative=negative or 0,
        ),
        priority=PriorityBreakdown(
            critical=critical or 0, high=high or 0, medium=medium or 0, low=low or 0,
        ),
        category=CategoryBreakdown(
            complaint=complaint or 0, support=support or 0, sales=sales or 0,
            refund=refund or 0, invoice=invoice or 0, feedback=feedback or 0,
            general=general or 0,
        ),
    )

@router.get("/trends", response_model=TrendsResponse)
def get_trends(
    days: int = Query(30, ge=7, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return daily sentiment trend data for the last N days."""
    since = datetime.utcnow() - timedelta(days=days)

    rows = (
        db.query(
            func.date(Email.received_at).label("date"),
            EmailAnalysis.sentiment,
            func.count(Email.id).label("count"),
        )
        .join(EmailAnalysis, Email.id == EmailAnalysis.email_id)
        .join(EmailIntegration, Email.integration_id == EmailIntegration.id)
        .filter(Email.received_at >= since)
        .filter(EmailIntegration.owner_user_id == current_user.id if current_user.role != "admin" else True)
        .group_by(func.date(Email.received_at), EmailAnalysis.sentiment)
        .order_by(func.date(Email.received_at))
        .all()
    )

    # Aggregate by date
    date_map: dict[str, dict] = {}
    for row in rows:
        d = str(row.date)
        if d not in date_map:
            date_map[d] = {"positive": 0, "neutral": 0, "negative": 0}
        date_map[d][row.sentiment] = row.count

    trends = [
        TrendPoint(
            date=d,
            positive=v["positive"],
            neutral=v["neutral"],
            negative=v["negative"],
            total=v["positive"] + v["neutral"] + v["negative"],
        )
        for d, v in sorted(date_map.items())
    ]

    return TrendsResponse(trends=trends, period_days=days)
