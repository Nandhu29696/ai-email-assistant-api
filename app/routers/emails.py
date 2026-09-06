"""
Emails router — CRUD operations and analysis trigger.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import String, cast
from sqlalchemy.orm import Session
from loguru import logger

from app.database import get_db, SessionLocal
from app.models.email import Email, EmailAnalysis, Notification, EmailReply
from app.schemas.email import EmailCreate, EmailOut, EmailListOut, EmailUpdateRequest
from app.services import (
    preprocess_email, analyze_sentiment, detect_emotions, classify_email,
    assign_priority, generate_summary, generate_reply, route_email,
    notification_manager,
)
from app.services.ai_client import get_model, ai_available
from app.services.response_validator import validate_auto_reply
from app.services.gmail_send import send_reply_via_gmail
from app.routers.reply_tracker import record_reply_sent
from app.models.email import Email, EmailAnalysis, Notification, EmailReply, EmailIntegration
from app.config import settings
from app.routers.auth import get_current_user
from app.models.user import User

router = APIRouter()


def _scoped_email_query(db: Session, current_user: User):
    query = db.query(Email)
    if current_user.role != "admin":
        query = query.join(EmailIntegration, Email.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    return query


def _add_notification_safe(
    db: Session,
    email_id_value,
    notif_type: str,
    title: str,
    message: str,
) -> Notification | None:
    """Create a notification even when DB email_id type drifts across environments.

    Some environments use UUID for notifications.email_id while others use int.
    We first try with email_id set, then retry with NULL to avoid dropping alerts.
    """
    notification = Notification(
        email_id=email_id_value,
        type=notif_type,
        title=title,
        message=message,
    )
    db.add(notification)
    try:
        db.commit()
        db.refresh(notification)
        return notification
    except Exception as exc:
        db.rollback()
        logger.warning(
            f"Notification insert with email_id failed; retrying without email_id. error={exc}"
        )

    fallback_notification = Notification(
        email_id=None,
        type=notif_type,
        title=title,
        message=message,
    )
    db.add(fallback_notification)
    try:
        db.commit()
        db.refresh(fallback_notification)
        return fallback_notification
    except Exception as exc:
        db.rollback()
        logger.error(f"Notification insert fallback failed: {exc}")
        return None


# ── Full AI analysis pipeline ─────────────────────────────────
async def _run_analysis_pipeline(email_id: int, db: Session | None = None):
    """Run complete AI pipeline for a given email.

    Accepts an existing *db* session for backward compatibility (router usage),
    but creates its own short-lived sessions internally so the pool connection
    is never held open across long-running async AI calls.
    """
    start = time.time()

    # ── Phase 1: load email fields then release the connection ────────────────
    _own_db = db is None
    _db = db if db is not None else SessionLocal()
    thread_context: list[str] = []
    try:
        email_obj = _db.query(Email).filter(Email.id == email_id).first()
        if not email_obj:
            return
        # Snapshot the fields we need; close session before AI calls
        subject      = email_obj.subject
        body_plain   = email_obj.body_plain
        body_html    = email_obj.body_html
        sender_email = email_obj.sender_email
        thread_id    = email_obj.thread_id

        # Fetch prior messages in the same thread if available
        if thread_id:
            prior_emails = (
                _db.query(Email.body_clean, Email.body_plain, Email.sender_email)
                .filter(Email.thread_id == thread_id, Email.id != email_id)
                .order_by(Email.received_at.asc())
                .limit(3)
                .all()
            )
            for pe in prior_emails:
                text_content = pe.body_clean or pe.body_plain or ""
                if text_content:
                    thread_context.append(f"From {pe.sender_email}: {text_content[:400]}")
    finally:
        if _own_db:
            _db.close()

    try:
        # ── Phase 2: all AI work — NO database connection held ────────────────
        clean = preprocess_email(body_plain, body_html)

        sentiment      = analyze_sentiment(clean)
        emotions       = detect_emotions(clean)
        classification = await classify_email(clean)
        priority       = assign_priority(
            sentiment.label,
            float(sentiment.score),
            emotions.primary_emotion,
            classification.category,
        )
        summary = await generate_summary(subject, clean, thread_context=thread_context)
        reply   = await generate_reply(
            subject, clean,
            classification.category, sentiment.label,
            thread_context=thread_context,
        )
        routing = route_email(
            classification.category, sentiment.label, priority.priority
        )
        elapsed = int((time.time() - start) * 1000)

        # ── Phase 3: persist results in a fresh short-lived session ───────────
        write_db = SessionLocal()
        try:
            email_obj2 = write_db.query(Email).filter(Email.id == email_id).first()
            if not email_obj2:
                return

            email_obj2.body_clean   = clean
            email_obj2.processed_at = datetime.now(timezone.utc)

            analysis = write_db.query(EmailAnalysis).filter(EmailAnalysis.email_id == email_id).first()
            if not analysis:
                analysis = EmailAnalysis(email_id=email_id)
                write_db.add(analysis)

            analysis.sentiment           = sentiment.label
            analysis.sentiment_score     = sentiment.score
            analysis.primary_emotion     = emotions.primary_emotion
            analysis.emotions_json       = [{"emotion": e.emotion, "score": e.score} for e in emotions.emotions]
            analysis.category            = classification.category
            analysis.category_confidence = classification.confidence
            analysis.priority            = priority.priority
            analysis.priority_score      = priority.score
            analysis.ai_summary          = summary
            analysis.suggested_reply     = reply
            analysis.routed_to           = routing.team
            analysis.routing_reason      = routing.reason
            analysis.model_version       = get_model() if ai_available() else "vader-rules-engine"
            analysis.processing_time_ms  = elapsed

            write_db.commit()

            # ── Phase 4: create notifications ─────────────────────────────────
            # 4a. Always create a "new_email" notification (if not already present)
            email_id_as_text = str(email_obj2.id)
            existing_new = (
                write_db.query(Notification)
                .filter(
                    cast(Notification.email_id, String) == email_id_as_text,
                    Notification.type == "new_email",
                )
                .first()
            )
            if not existing_new:
                new_notif = _add_notification_safe(
                    write_db,
                    email_obj2.id,
                    "new_email",
                    f"📧 New email: {subject[:60]}",
                    f"From: {sender_email} | {sentiment.label.capitalize()} | {classification.category.capitalize()}",
                )
                if new_notif:
                    owner_user_id = email_obj2.integration.owner_user_id if email_obj2.integration else None
                    await notification_manager.broadcast_notification({
                        "id": new_notif.id,
                        "user_id": owner_user_id,
                        "email_id": new_notif.email_id,
                        "type": new_notif.type,
                        "title": new_notif.title,
                        "message": new_notif.message or "",
                        "is_read": new_notif.is_read,
                        "created_at": new_notif.created_at.isoformat(),
                    })

            # 4b. Extra alert notification for urgent/negative
            should_alert = (
                (priority.priority in ("critical", "high") and settings.NOTIFY_ON_CRITICAL) or
                (sentiment.label == "negative" and settings.NOTIFY_ON_NEGATIVE)
            )
            if should_alert:
                alert_type = "urgent" if priority.priority == "critical" else "negative_sentiment"
                alert = _add_notification_safe(
                    write_db,
                    email_obj2.id,
                    alert_type,
                    f"⚠️ {priority.priority.upper()}: {subject[:60]}",
                    f"From: {sender_email} | Sentiment: {sentiment.label} | Category: {classification.category}",
                )
                if alert:
                    owner_user_id = email_obj2.integration.owner_user_id if email_obj2.integration else None
                    await notification_manager.broadcast_notification({
                        "id": alert.id,
                        "user_id": owner_user_id,
                        "email_id": alert.email_id,
                        "type": alert.type,
                        "title": alert.title,
                        "message": alert.message or "",
                        "is_read": alert.is_read,
                        "created_at": alert.created_at.isoformat(),
                    })

            # ── Phase 5: Automated AI Validation & Instant Auto-Response ─────
            if settings.AUTO_REPLY_ENABLED and reply and email_obj2.integration_id:
                val_result = await validate_auto_reply(
                    subject=subject,
                    email_body=clean,
                    draft_reply=reply,
                    category=classification.category,
                    sentiment_label=sentiment.label,
                    priority=priority.priority,
                )

                if val_result.is_valid:
                    auto_reply = EmailReply(
                        email_id=email_obj2.id,
                        subject=f"Re: {subject}",
                        body=reply,
                        is_draft=False,
                        sent_at=datetime.now(timezone.utc),
                    )
                    write_db.add(auto_reply)
                    write_db.commit()
                    write_db.refresh(auto_reply)

                    sent_ok, err = send_reply_via_gmail(email_obj2, auto_reply)
                    if sent_ok:
                        record_reply_sent(write_db, email_id=email_obj2.id, reply_id=auto_reply.id)
                        logger.info(f"🤖 [Auto-Reply] AI auto-replied to email {email_id} (Score: {val_result.confidence_score})")
                        auto_notif = _add_notification_safe(
                            write_db,
                            email_obj2.id,
                            "auto_replied",
                            f"🤖 AI Auto-Replied: {subject[:50]}",
                            f"Sent to {sender_email} | AI Confidence: {int(val_result.confidence_score * 100)}%",
                        )
                        if auto_notif:
                            owner_user_id = email_obj2.integration.owner_user_id if email_obj2.integration else None
                            await notification_manager.broadcast_notification({
                                "id": auto_notif.id,
                                "user_id": owner_user_id,
                                "email_id": auto_notif.email_id,
                                "type": auto_notif.type,
                                "title": auto_notif.title,
                                "message": auto_notif.message or "",
                                "is_read": auto_notif.is_read,
                                "created_at": auto_notif.created_at.isoformat(),
                            })
                    else:
                        logger.warning(f"[Auto-Reply] Send failed for email {email_id}: {err}")
                        auto_reply.is_draft = True
                        auto_reply.sent_at = None
                        write_db.commit()
                else:
                    logger.info(f"[Auto-Reply] AI validation held email {email_id} for review: {val_result.reason}")

            logger.info(f"Analysis complete for email {email_id} ({elapsed}ms)")

        except Exception as exc:
            logger.error(f"Analysis write failed for {email_id}: {exc}")
            write_db.rollback()
        finally:
            write_db.close()

    except Exception as exc:
        logger.error(f"Analysis pipeline failed for {email_id}: {exc}")


# ── Routes ────────────────────────────────────────────────────
@router.get("", response_model=EmailListOut)
def list_emails(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sentiment: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    is_read: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _scoped_email_query(db, current_user)

    if is_read is not None:
        query = query.filter(Email.is_read == is_read)
    if search:
        query = query.filter(
            Email.subject.ilike(f"%{search}%") |
            Email.sender_email.ilike(f"%{search}%") |
            Email.body_clean.ilike(f"%{search}%")
        )
    if sentiment:
        query = query.join(EmailAnalysis).filter(EmailAnalysis.sentiment == sentiment)
    if priority:
        query = query.join(EmailAnalysis).filter(EmailAnalysis.priority == priority)
    if category:
        query = query.join(EmailAnalysis).filter(EmailAnalysis.category == category)

    total = query.count()
    items = (
        query.order_by(Email.received_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return EmailListOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/{email_id}", response_model=EmailOut)
def get_email(email_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    email_obj = _scoped_email_query(db, current_user).filter(Email.id == email_id).first()
    if not email_obj:
        raise HTTPException(status_code=404, detail="Email not found")
    return email_obj


@router.post("/{email_id}/analyze")
async def analyze_email(
    email_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger full AI analysis pipeline for an email."""
    email_obj = _scoped_email_query(db, current_user).filter(Email.id == email_id).first()
    if not email_obj:
        raise HTTPException(status_code=404, detail="Email not found")

    # Pipeline manages its own DB sessions to avoid holding a connection
    # across long-running async AI calls.
    background_tasks.add_task(_run_analysis_pipeline, email_id)
    return {"message": "Analysis started", "email_id": email_id}


@router.patch("/{email_id}", response_model=EmailOut)
def update_email(
    email_id: int,
    payload: EmailUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    email_obj = _scoped_email_query(db, current_user).filter(Email.id == email_id).first()
    if not email_obj:
        raise HTTPException(status_code=404, detail="Email not found")

    if payload.is_read is not None:
        email_obj.is_read = payload.is_read
    if payload.is_archived is not None:
        email_obj.is_archived = payload.is_archived

    db.commit()
    db.refresh(email_obj)
    return email_obj


@router.post("/ingest", response_model=EmailOut, status_code=201)
async def ingest_email(
    payload: EmailCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Ingest a new email and trigger analysis."""
    existing = db.query(Email).filter(Email.message_id == payload.message_id).first()
    if existing:
        return existing

    email_obj = Email(**payload.model_dump())
    db.add(email_obj)
    db.commit()
    db.refresh(email_obj)

    background_tasks.add_task(_run_analysis_pipeline, email_obj.id)
    return email_obj
