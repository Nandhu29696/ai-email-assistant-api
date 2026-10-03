"""
Dashboard — how many emails went through each rule, plus AI category/sentiment
breakdowns and the health of the automatic pickup.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.document_intake import EmailBatch
from app.models.email import AllowedDomain, EmailIntegration
from app.models.user import User
from app.routers.auth import get_current_user

router = APIRouter()

OUTCOMES = [
    "PROCESSED", "DOMAIN_NOT_ALLOWED", "NO_ATTACHMENT", "INVALID_FILE_TYPE",
    "INVALID_ATTACHMENTS", "SENDER_NOT_VERIFIED", "AUTOMATED_MESSAGE", "SYSTEM_ERROR",
]


def _scoped(query, current_user: User):
    if current_user.role != "admin":
        query = query.join(EmailIntegration, EmailBatch.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    return query


def _counts(db: Session, current_user: User, column, since: datetime) -> dict[str, int]:
    rows = _scoped(db.query(column, func.count(EmailBatch.id)), current_user).filter(
        EmailBatch.received_datetime >= since,
    ).group_by(column).all()
    return {(key or "unknown"): count for key, count in rows}


@router.get("/summary")
def summary(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    by_status = _counts(db, current_user, EmailBatch.status, since)
    by_outcome = _counts(db, current_user, EmailBatch.outcome, since)

    day = func.date(EmailBatch.received_datetime)
    daily_rows = _scoped(db.query(day, EmailBatch.status, func.count(EmailBatch.id)), current_user).filter(
        EmailBatch.received_datetime >= since,
    ).group_by(day, EmailBatch.status).all()
    daily: dict[str, dict[str, int]] = {}
    for date_value, status, count in daily_rows:
        key = str(date_value)
        daily.setdefault(key, {"date": key, "SUCCESS": 0, "REJECTED": 0, "FAILED": 0, "OTHER": 0})
        bucket = status if status in ("SUCCESS", "REJECTED", "FAILED") else "OTHER"
        daily[key][bucket] += count

    mailboxes = db.query(EmailIntegration).filter(EmailIntegration.is_active == True)
    if current_user.role != "admin":
        mailboxes = mailboxes.filter(EmailIntegration.owner_user_id == current_user.id)
    mailboxes = mailboxes.all()
    domains_configured = db.query(AllowedDomain.id).filter(AllowedDomain.is_active == True).count()

    return {
        "days": days,
        "total": sum(by_status.values()),
        "by_status": by_status,
        "by_outcome": {key: by_outcome.get(key, 0) for key in OUTCOMES},
        "by_category": _counts(db, current_user, EmailBatch.email_category, since),
        "by_sentiment": _counts(db, current_user, EmailBatch.sentiment, since),
        "by_priority": _counts(db, current_user, EmailBatch.priority, since),
        "daily": sorted(daily.values(), key=lambda item: item["date"]),
        "pickup": {
            "automatic": settings.RUN_BACKGROUND_WORKERS,
            "interval_seconds": settings.FETCH_INTERVAL_SECONDS,
            "mailboxes": [
                {
                    "id": m.id,
                    "email_address": m.email_address,
                    "provider": m.provider,
                    "health_status": m.health_status or "unknown",
                    "health_message": m.health_message,
                    "last_sync_at": m.last_sync_at.isoformat() if m.last_sync_at else None,
                    "last_email_processed_at": m.last_email_processed_at.isoformat() if m.last_email_processed_at else None,
                }
                for m in mailboxes
            ],
        },
        "allowed_domains_configured": domains_configured,
        "ops_alerts_configured": bool(settings.OPS_ALERT_WEBHOOK_URL),
        "retention_days_default": settings.DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS,
    }
