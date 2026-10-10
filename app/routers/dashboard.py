"""
Dashboard — how many emails went through each rule, plus AI category/sentiment
breakdowns, a per-mailbox overview and the health of the automatic pickup.

Admins see every mailbox; clients see only the mailboxes they own. Every number
can be narrowed to one mailbox with ``integration_id``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.access import scope_mailboxes
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
IN_PROGRESS = ("RECEIVED", "PROCESSING", "REPROCESSING")


def _scoped(query, current_user: User, integration_id: int | None = None):
    if current_user.role != "admin":
        query = scope_mailboxes(query.join(EmailIntegration, EmailBatch.integration_id == EmailIntegration.id), current_user)
    if integration_id is not None:
        query = query.filter(EmailBatch.integration_id == integration_id)
    return query


def _counts(db: Session, current_user: User, column, since: datetime, integration_id: int | None) -> dict[str, int]:
    rows = _scoped(db.query(column, func.count(EmailBatch.id)), current_user, integration_id).filter(
        EmailBatch.received_datetime >= since,
    ).group_by(column).all()
    return {(key or "unknown"): count for key, count in rows}


def _visible_mailboxes(db: Session, current_user: User) -> list[EmailIntegration]:
    """Mailboxes this user may see: active ones, plus disconnected ones that still have emails."""
    with_emails = db.query(EmailBatch.integration_id).filter(EmailBatch.integration_id.isnot(None)).distinct()
    q = db.query(EmailIntegration).filter(
        (EmailIntegration.is_active == True) | EmailIntegration.id.in_(with_emails)  # noqa: E712
    )
    q = scope_mailboxes(q, current_user)
    return q.order_by(EmailIntegration.email_address).all()


def _per_mailbox(db: Session, mailboxes: list[EmailIntegration], since: datetime) -> list[dict]:
    """Counts per mailbox for the period: received, processed, rejected, needs attention, ignored."""
    ids = [m.id for m in mailboxes]
    counts: dict[int, dict[str, int]] = {i: {} for i in ids}
    last_received: dict[int, datetime] = {}
    if ids:
        rows = db.query(EmailBatch.integration_id, EmailBatch.status, func.count(EmailBatch.id)).filter(
            EmailBatch.integration_id.in_(ids), EmailBatch.received_datetime >= since,
        ).group_by(EmailBatch.integration_id, EmailBatch.status).all()
        for mailbox_id, status, n in rows:
            counts[mailbox_id][status] = n
        for mailbox_id, latest in db.query(EmailBatch.integration_id, func.max(EmailBatch.received_datetime)).filter(
            EmailBatch.integration_id.in_(ids),
        ).group_by(EmailBatch.integration_id).all():
            last_received[mailbox_id] = latest
    owners = {u.id: u for u in db.query(User).filter(User.id.in_([m.owner_user_id for m in mailboxes if m.owner_user_id]))}

    result = []
    for m in mailboxes:
        c = counts.get(m.id, {})
        owner = owners.get(m.owner_user_id)
        latest = last_received.get(m.id)
        result.append({
            "id": m.id,
            "email_address": m.email_address,
            "provider": m.provider,
            "mailbox_type": m.mailbox_type,
            "batch_prefix": m.batch_prefix,
            "is_active": bool(m.is_active),
            "owner": (owner.full_name or owner.username) if owner else None,
            "health_status": m.health_status or "unknown",
            "health_message": m.health_message,
            "last_sync_at": m.last_sync_at.isoformat() if m.last_sync_at else None,
            "last_email_at": latest.isoformat() if latest else None,
            "total": sum(c.values()),
            "processed": c.get("SUCCESS", 0),
            "rejected": c.get("REJECTED", 0),
            "needs_attention": c.get("FAILED", 0),
            "ignored": c.get("IGNORED", 0),
            "in_progress": sum(c.get(s, 0) for s in IN_PROGRESS),
        })
    return result


_BUCKETS = ("SUCCESS", "REJECTED", "FAILED", "IGNORED", "IN_PROGRESS", "OTHER")


def _month_range(start: datetime, end: datetime) -> list[str]:
    """Every calendar month (YYYY-MM) from start to end, inclusive."""
    year, month, keys = start.year, start.month, []
    while (year, month) <= (end.year, end.month):
        keys.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return keys


def _first_of_month(months_back: int, now: datetime) -> datetime:
    """Midnight UTC on the 1st of the month `months_back` months before now's month."""
    index = now.year * 12 + now.month - 1 - months_back
    return datetime(index // 12, index % 12 + 1, 1, tzinfo=timezone.utc)


def _monthly(days: "Iterable[dict[str, int | str]]", start: datetime | None = None,
             end: datetime | None = None) -> list[dict]:
    """Roll the per-day buckets up into calendar months (YYYY-MM), oldest first.

    With start/end, months without any email are included as zero rows so the
    chart shows the whole period.
    """
    months: dict[str, dict] = {}
    if start and end:
        for key in _month_range(start, end):
            months[key] = {"month": key, **{b: 0 for b in _BUCKETS}}
    for day in days:
        key = str(day["date"])[:7]
        row = months.setdefault(key, {"month": key, **{b: 0 for b in _BUCKETS}})
        for bucket in _BUCKETS:
            row[bucket] += int(day.get(bucket, 0))
    return [months[k] for k in sorted(months)]


@router.get("/summary")
def summary(
    days: int = Query(30, ge=1, le=365),
    months: Optional[int] = Query(None, ge=1, le=24, description="Calendar months incl. the current one (overrides days)"),
    integration_id: Optional[int] = Query(None, description="Only this mailbox (default: all visible mailboxes)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    since = _first_of_month(months - 1, now) if months else now - timedelta(days=days)
    by_status = _counts(db, current_user, EmailBatch.status, since, integration_id)
    by_outcome = _counts(db, current_user, EmailBatch.outcome, since, integration_id)

    day = func.date(EmailBatch.received_datetime)
    daily_rows = _scoped(db.query(day, EmailBatch.status, func.count(EmailBatch.id)), current_user, integration_id).filter(
        EmailBatch.received_datetime >= since,
    ).group_by(day, EmailBatch.status).all()
    daily: dict[str, dict[str, int]] = {}
    for date_value, status, count in daily_rows:
        key = str(date_value)
        daily.setdefault(key, {"date": key, "SUCCESS": 0, "REJECTED": 0, "FAILED": 0, "IGNORED": 0, "IN_PROGRESS": 0, "OTHER": 0})
        if status in ("SUCCESS", "REJECTED", "FAILED", "IGNORED"):
            bucket = status
        elif status in IN_PROGRESS:
            bucket = "IN_PROGRESS"
        else:
            bucket = "OTHER"
        daily[key][bucket] += count

    visible = _visible_mailboxes(db, current_user)
    selected = [m for m in visible if integration_id is None or m.id == integration_id]
    domains_configured = db.query(AllowedDomain.id).filter(AllowedDomain.is_active == True).count()  # noqa: E712

    return {
        "days": days,
        "integration_id": integration_id,
        "total": sum(by_status.values()),
        "by_status": by_status,
        # Every email is in exactly one of these, so they always add up to "total".
        "status_totals": {
            "processed": by_status.get("SUCCESS", 0),
            "rejected": by_status.get("REJECTED", 0),
            "needs_attention": by_status.get("FAILED", 0),
            "ignored": by_status.get("IGNORED", 0),
            "in_progress": sum(by_status.get(s, 0) for s in IN_PROGRESS),
            "other": sum(n for s, n in by_status.items()
                         if s not in ("SUCCESS", "REJECTED", "FAILED", "IGNORED", *IN_PROGRESS)),
        },
        "by_outcome": {key: by_outcome.get(key, 0) for key in OUTCOMES},
        "by_category": _counts(db, current_user, EmailBatch.email_category, since, integration_id),
        "by_sentiment": _counts(db, current_user, EmailBatch.sentiment, since, integration_id),
        "by_priority": _counts(db, current_user, EmailBatch.priority, since, integration_id),
        "daily": sorted(daily.values(), key=lambda item: item["date"]),
        "monthly": _monthly(daily.values(), since, now),
        # Overview of every mailbox the user may see (not narrowed by integration_id), for the
        # mailbox table and the mailbox selector.
        "by_mailbox": _per_mailbox(db, visible, since),
        "pickup": {
            "automatic": settings.RUN_BACKGROUND_WORKERS,
            "interval_seconds": settings.FETCH_INTERVAL_SECONDS,
            "mailboxes": [
                {
                    "id": m.id,
                    "email_address": m.email_address,
                    "provider": m.provider,
                    "interval_seconds": m.pickup_interval_seconds,
                    "health_status": m.health_status or "unknown",
                    "health_message": m.health_message,
                    "last_sync_at": m.last_sync_at.isoformat() if m.last_sync_at else None,
                    "last_email_processed_at": m.last_email_processed_at.isoformat() if m.last_email_processed_at else None,
                }
                for m in selected if m.is_active
            ],
        },
        "allowed_domains_configured": domains_configured,
        "ops_alerts_configured": bool(settings.OPS_ALERT_WEBHOOK_URL),
        "retention_days_default": settings.DOCUMENT_INTAKE_DEFAULT_RETENTION_DAYS,
    }
