"""
Replies router — create, list, and send email replies.
"""
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.email import Email, EmailReply, EmailIntegration
from app.services.gmail_send import send_reply_via_gmail
from app.schemas.email import ReplyCreate, ReplyOut
from app.routers.reply_tracker import record_reply_sent
from app.routers.auth import get_current_user
from app.models.user import User

router = APIRouter()


def _get_owned_email(email_id: int, db: Session, current_user: User) -> Email:
    query = db.query(Email).filter(Email.id == email_id)
    if current_user.role != "admin":
        query = query.join(EmailIntegration, Email.integration_id == EmailIntegration.id).filter(
            EmailIntegration.owner_user_id == current_user.id
        )
    email_obj = query.first()
    if not email_obj:
        raise HTTPException(status_code=404, detail="Email not found")
    return email_obj


@router.get("/{email_id}/replies", response_model=list[ReplyOut])
def list_replies(email_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Return all drafts and sent replies for an email, newest first."""
    _get_owned_email(email_id, db, current_user)
    return (
        db.query(EmailReply)
        .filter(EmailReply.email_id == email_id)
        .order_by(EmailReply.created_at.desc())
        .all()
    )


@router.post("/{email_id}/replies", response_model=ReplyOut, status_code=201)
def create_reply(
    email_id: int,
    payload: ReplyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a reply draft or mark it as sent immediately (payload.send=True)."""
    email_obj = _get_owned_email(email_id, db, current_user)

    reply = EmailReply(
        email_id=email_id,
        subject=payload.subject or f"Re: {email_obj.subject}",
        body=payload.body,
        attachments_json=payload.attachments or [],
        is_draft=True,
        sent_at=None,
    )
    db.add(reply)
    db.commit()
    db.refresh(reply)

    if payload.send:
        sent_ok, err = send_reply_via_gmail(email_obj, reply)

        if not sent_ok:

            if err == "invalid_scope":
                raise HTTPException(
                    status_code=403,
                    detail="Gmail integration is missing gmail.send permission. Reconnect Gmail."
                )

            if err == "rate_limit_exceeded":
                raise HTTPException(
                    status_code=429,
                    detail="Gmail sending limit exceeded. Please wait a few minutes and try again."
                )

            raise HTTPException(
                status_code=502,
                detail=f"Failed to send reply: {err}"
            )

        reply.is_draft = False
        reply.sent_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(reply)

        try:
            record_reply_sent(db, email_id=email_id, reply_id=reply.id)
        except Exception:
            pass

    return reply


@router.patch("/{email_id}/replies/{reply_id}", response_model=ReplyOut)
def update_reply(
    email_id: int,
    reply_id: int,
    payload: ReplyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Edit an existing draft reply."""
    email_obj = _get_owned_email(email_id, db, current_user)
    reply = (
        db.query(EmailReply)
        .filter(EmailReply.id == reply_id, EmailReply.email_id == email_id)
        .first()
    )
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    if not reply.is_draft:
        raise HTTPException(status_code=400, detail="Cannot edit a sent reply")

    if payload.subject is not None:
        reply.subject = payload.subject
    reply.body = payload.body
    reply.attachments_json = payload.attachments or reply.attachments_json

    if payload.send:
        sent_ok, err = send_reply_via_gmail(email_obj, reply)
        if not sent_ok:
            if "invalid_scope" in (err or ""):
                raise HTTPException(
                    status_code=502,
                    detail="Send failed: integration missing `gmail.send` scope — reauthorize the Gmail integration with send permission",
                )
            raise HTTPException(status_code=502, detail=f"Failed to send reply: {err}")

        reply.is_draft = False
        reply.sent_at = datetime.now(timezone.utc)
        try:
            record_reply_sent(db, email_id=email_id, reply_id=reply.id)
        except Exception:
            pass

    db.commit()
    db.refresh(reply)
    return reply


@router.post("/{email_id}/replies/{reply_id}/send", response_model=ReplyOut)
def send_reply(
    email_id: int,
    reply_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a draft reply as sent."""
    reply = (
        db.query(EmailReply)
        .filter(EmailReply.id == reply_id, EmailReply.email_id == email_id)
        .first()
    )
    if not reply:
        raise HTTPException(status_code=404, detail="Reply not found")
    if not reply.is_draft:
        raise HTTPException(status_code=400, detail="Reply already sent")

    # First, fetch the email and attempt to send via provider. Only mark as sent
    # in the DB if the provider send succeeds.
    email_obj = _get_owned_email(email_id, db, current_user)

    sent_ok, err = send_reply_via_gmail(email_obj, reply)
    if not sent_ok:
        # Provide actionable message when it's a permissions/scope problem.
        if "invalid_scope" in (err or ""):
            raise HTTPException(
                status_code=502,
                detail="Send failed: integration missing `gmail.send` scope — reauthorize the Gmail integration with send permission",
            )
        raise HTTPException(status_code=502, detail=f"Failed to send reply: {err}")

    # Provider send succeeded — mark reply as sent in DB and return
    reply.is_draft = False
    reply.sent_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reply)

    try:
        record_reply_sent(db, email_id=email_id, reply_id=reply.id)
    except Exception:
        pass

    return reply
