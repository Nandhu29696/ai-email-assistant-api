"""
Reply Tracker router — SLA compliance, response time analytics, status management.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.email import Email, EmailReply, EmailResponseTracker, EmailAnalysis, EmailIntegration
from app.routers.auth import get_current_user, require_admin, _log_audit, _get_ip
from app.models.user import User

router = APIRouter()

# SLA thresholds by priority (minutes)
SLA_THRESHOLDS = {
    "critical": 60,    # 1 hour
    "high": 240,       # 4 hours
    "medium": 1440,    # 24 hours
    "low": 4320,       # 72 hours
}


class TrackerUpdateRequest(BaseModel):
    status: Optional[str] = None   # pending | replied | escalated | ignored
    escalated_to: Optional[str] = None
    notes: Optional[str] = None


def _ensure_tracker(db: Session, email_id: int) -> EmailResponseTracker:
    """Get or create a tracker row for an email."""
    tracker = db.query(EmailResponseTracker).filter(
        EmailResponseTracker.email_id == email_id
    ).first()
    if not tracker:
        tracker = EmailResponseTracker(email_id=email_id, status="pending")
        db.add(tracker)
        db.commit()
        db.refresh(tracker)
    return tracker


def record_reply_sent(db: Session, email_id: int, reply_id: int, user_id: int | None = None) -> EmailResponseTracker:
    """Update tracker when an email reply has been sent."""
    tracker = _ensure_tracker(db, email_id)
    email_obj = db.query(Email).filter(Email.id == email_id).first()
    analysis = email_obj.analysis if email_obj else None

    now = datetime.now(timezone.utc)
    received_at = email_obj.received_at if email_obj else now
    diff_minutes = max(0, int((now - received_at).total_seconds() / 60))

    priority = analysis.priority if analysis else "medium"
    threshold = SLA_THRESHOLDS.get(priority, 1440)

    tracker.reply_id = reply_id
    tracker.responded_by_user_id = user_id
    tracker.status = "replied"
    if tracker.first_response_minutes is None:
        tracker.first_response_minutes = diff_minutes
    tracker.sla_breach = diff_minutes > threshold

    db.commit()
    db.refresh(tracker)
    return tracker


def evaluate_all_pending_slas(db: Session) -> int:
    """Batch-check pending emails and mark SLA breaches."""
    now = datetime.now(timezone.utc)
    pending_trackers = (
        db.query(EmailResponseTracker)
        .join(Email, EmailResponseTracker.email_id == Email.id)
        .filter(EmailResponseTracker.status == "pending", EmailResponseTracker.sla_breach == False)
        .all()
    )

    breach_count = 0
    for t in pending_trackers:
        email = t.email
        if not email or not email.received_at:
            continue
        analysis = email.analysis
        priority = analysis.priority if analysis else "medium"
        threshold = SLA_THRESHOLDS.get(priority, 1440)
        elapsed_minutes = int((now - email.received_at).total_seconds() / 60)

        if elapsed_minutes > threshold:
            t.sla_breach = True
            breach_count += 1

    if breach_count > 0:
        db.commit()
    return breach_count


@router.get("")
def list_trackers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    sla_breach: Optional[bool] = Query(None),
    days: int = Query(30, ge=1, le=90),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        db.query(EmailResponseTracker)
        .join(Email, EmailResponseTracker.email_id == Email.id)
        .filter(Email.received_at >= since)
    )
    if current_user.role != "admin":
        q = q.join(EmailIntegration, Email.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )

    if status:
        q = q.filter(EmailResponseTracker.status == status)
    if sla_breach is not None:
        q = q.filter(EmailResponseTracker.sla_breach == sla_breach)
    if priority:
        q = q.join(EmailAnalysis, Email.id == EmailAnalysis.email_id).filter(
            EmailAnalysis.priority == priority
        )

    total = q.count()
    items = (
        q.order_by(Email.received_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    result = []
    for t in items:
        email = t.email
        analysis = email.analysis if email else None
        result.append({
            "tracker_id": t.id,
            "email_id": t.email_id,
            "subject": email.subject if email else None,
            "sender_email": email.sender_email if email else None,
            "received_at": email.received_at.isoformat() if email and email.received_at else None,
            "status": t.status,
            "priority": analysis.priority if analysis else None,
            "first_response_minutes": t.first_response_minutes,
            "sla_threshold_minutes": SLA_THRESHOLDS.get(analysis.priority, 1440) if analysis else 1440,
            "sla_breach": t.sla_breach,
            "escalated_to": t.escalated_to,
            "notes": t.notes,
            "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        })

    return {"total": total, "page": page, "page_size": page_size, "items": result}


@router.get("/summary")
def tracker_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    days: int = Query(30, ge=1, le=90),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Status breakdown
    status_rows = (
        db.query(EmailResponseTracker.status, func.count(EmailResponseTracker.id))
        .join(Email, EmailResponseTracker.email_id == Email.id)
        .filter(Email.received_at >= since)
        .group_by(EmailResponseTracker.status)
        .all()
    )
    if current_user.role != "admin":
        status_rows = (
            db.query(EmailResponseTracker.status, func.count(EmailResponseTracker.id))
            .join(Email, EmailResponseTracker.email_id == Email.id)
            .join(EmailIntegration, Email.integration_id == EmailIntegration.id)
            .filter(
                Email.received_at >= since,
                EmailIntegration.owner_user_id == current_user.id,
            )
            .group_by(EmailResponseTracker.status)
            .all()
        )
    status_map = {r[0]: r[1] for r in status_rows}

    total_tracked = sum(status_map.values())
    breach_query = db.query(func.count(EmailResponseTracker.id)).join(
        Email, EmailResponseTracker.email_id == Email.id
    ).filter(
        Email.received_at >= since,
        EmailResponseTracker.sla_breach == True,
    )
    if current_user.role != "admin":
        breach_query = breach_query.join(EmailIntegration, Email.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    sla_breaches = breach_query.scalar() or 0

    avg_query = db.query(func.avg(EmailResponseTracker.first_response_minutes)).join(
        Email, EmailResponseTracker.email_id == Email.id
    ).filter(
        Email.received_at >= since,
        EmailResponseTracker.first_response_minutes.isnot(None),
    )
    if current_user.role != "admin":
        avg_query = avg_query.join(EmailIntegration, Email.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    avg_response = avg_query.scalar() or 0

    # Priority breakdown of breaches
    breach_by_priority = (
        db.query(EmailAnalysis.priority, func.count(EmailResponseTracker.id))
        .join(EmailResponseTracker, EmailAnalysis.email_id == EmailResponseTracker.email_id)
        .join(Email, EmailResponseTracker.email_id == Email.id)
        .filter(
            Email.received_at >= since,
            EmailResponseTracker.sla_breach == True,
        )
        .group_by(EmailAnalysis.priority)
        .all()
    )
    if current_user.role != "admin":
        breach_by_priority = (
            db.query(EmailAnalysis.priority, func.count(EmailResponseTracker.id))
            .join(EmailResponseTracker, EmailAnalysis.email_id == EmailResponseTracker.email_id)
            .join(Email, EmailResponseTracker.email_id == Email.id)
            .join(EmailIntegration, Email.integration_id == EmailIntegration.id)
            .filter(
                Email.received_at >= since,
                EmailResponseTracker.sla_breach == True,
                EmailIntegration.owner_user_id == current_user.id,
            )
            .group_by(EmailAnalysis.priority)
            .all()
        )

    return {
        "period_days": days,
        "total_tracked": total_tracked,
        "status_breakdown": status_map,
        "sla_breaches": sla_breaches,
        "sla_breach_rate_pct": round(sla_breaches / total_tracked * 100, 1) if total_tracked else 0,
        "avg_response_minutes": round(float(avg_response), 1),
        "breach_by_priority": [{"priority": p, "count": c} for p, c in breach_by_priority],
    }


@router.get("/{email_id}")
def get_tracker(
    email_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    email_query = db.query(Email).filter(Email.id == email_id)
    if current_user.role != "admin":
        email_query = email_query.join(EmailIntegration, Email.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    email = email_query.first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    tracker = _ensure_tracker(db, email_id)
    analysis = email.analysis

    return {
        "tracker_id": tracker.id,
        "email_id": email_id,
        "status": tracker.status,
        "priority": analysis.priority if analysis else None,
        "sla_threshold_minutes": SLA_THRESHOLDS.get(analysis.priority, 1440) if analysis else 1440,
        "first_response_minutes": tracker.first_response_minutes,
        "sla_breach": tracker.sla_breach,
        "escalated_to": tracker.escalated_to,
        "notes": tracker.notes,
        "responded_by_user_id": tracker.responded_by_user_id,
        "updated_at": tracker.updated_at.isoformat() if tracker.updated_at else None,
    }


@router.patch("/{email_id}")
def update_tracker(
    email_id: int,
    request: Request,
    payload: TrackerUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    email_query = db.query(Email).filter(Email.id == email_id)
    if current_user.role != "admin":
        email_query = email_query.join(EmailIntegration, Email.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    email = email_query.first()
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")

    tracker = _ensure_tracker(db, email_id)
    valid_statuses = {"pending", "replied", "escalated", "ignored"}

    if payload.status and payload.status not in valid_statuses:
        raise HTTPException(status_code=422, detail=f"status must be one of {valid_statuses}")

    if payload.status:
        tracker.status = payload.status
    if payload.escalated_to is not None:
        tracker.escalated_to = payload.escalated_to
        if payload.status is None:
            tracker.status = "escalated"
    if payload.notes is not None:
        tracker.notes = payload.notes

    tracker.responded_by_user_id = current_user.id

    # If marking as replied and no response time recorded yet, calculate it
    if tracker.status == "replied" and tracker.first_response_minutes is None:
        if email.received_at:
            now = datetime.now(timezone.utc)
            received = email.received_at.replace(tzinfo=timezone.utc) if email.received_at.tzinfo is None else email.received_at
            delta = now - received
            tracker.first_response_minutes = int(delta.total_seconds() / 60)

            # Check SLA breach
            analysis = email.analysis
            if analysis and analysis.priority:
                threshold = SLA_THRESHOLDS.get(analysis.priority, 1440)
                tracker.sla_breach = tracker.first_response_minutes > threshold

    db.commit()
    db.refresh(tracker)
    _log_audit(db, "reply_tracker_updated", current_user.id, "email", email_id,
               _get_ip(request), request.headers.get("User-Agent", ""),
               details={"status": tracker.status})

    return {"message": "Tracker updated", "status": tracker.status}


@router.post("/sync")
def sync_trackers(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Admin: scan all emails and auto-create tracker rows.
    Also auto-mark emails that have a sent reply as 'replied'.
    """
    emails = db.query(Email).all()
    created = 0
    updated = 0

    for email in emails:
        tracker = db.query(EmailResponseTracker).filter(
            EmailResponseTracker.email_id == email.id
        ).first()

        if not tracker:
            tracker = EmailResponseTracker(email_id=email.id, status="pending")
            db.add(tracker)
            created += 1

        # Check if a sent reply exists
        sent_reply = (
            db.query(EmailReply)
            .filter(EmailReply.email_id == email.id, EmailReply.is_draft == False)
            .order_by(EmailReply.sent_at.asc())
            .first()
        )

        if sent_reply and tracker.status == "pending":
            tracker.status = "replied"
            if sent_reply.sent_at and email.received_at:
                received = email.received_at.replace(tzinfo=timezone.utc) if email.received_at.tzinfo is None else email.received_at
                sent = sent_reply.sent_at.replace(tzinfo=timezone.utc) if sent_reply.sent_at.tzinfo is None else sent_reply.sent_at
                minutes = int((sent - received).total_seconds() / 60)
                tracker.first_response_minutes = max(0, minutes)
                analysis = email.analysis
                if analysis and analysis.priority:
                    threshold = SLA_THRESHOLDS.get(analysis.priority, 1440)
                    tracker.sla_breach = tracker.first_response_minutes > threshold
            tracker.reply_id = sent_reply.id
            updated += 1

    db.commit()
    return {"message": f"Sync complete: {created} created, {updated} updated"}
