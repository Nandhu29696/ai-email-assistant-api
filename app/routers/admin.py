"""
Admin router — user management, system stats. Admin access required for all endpoints.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.user import User, UserSession, AuditLog
from app.models.document_intake import EmailBatch, EmailBatchEvent
from app.routers.auth import (
    require_admin, hash_password, _log_audit, _get_ip,
    validate_password_strength, VALID_ROLES, _valid_client_id,
)
from app.schemas.user import UserOut

router = APIRouter()


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    client_id: Optional[int] = None   # for role "user": the client it belongs to
    is_active: Optional[bool] = None
    new_password: Optional[str] = None
    reset_mfa: Optional[bool] = None   # admin recovery for a lost authenticator device


def _active_admin_count(db: Session, exclude_user_id: int | None = None) -> int:
    q = db.query(func.count(User.id)).filter(User.role == "admin", User.is_active == True)
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return q.scalar() or 0


# ── User management ───────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    client_id: Optional[int] = Query(None, description="Only the users of this client"),
    is_active: Optional[bool] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    q = db.query(User)
    if search:
        q = q.filter(
            User.username.ilike(f"%{search}%") |
            User.email.ilike(f"%{search}%") |
            User.full_name.ilike(f"%{search}%")
        )
    if role:
        q = q.filter(User.role == role)
    if client_id is not None:
        q = q.filter(User.client_id == client_id)
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    return q.order_by(User.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    request: Request,
    payload: UserUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == admin.id:
        if payload.role is not None and payload.role != "admin":
            raise HTTPException(status_code=400, detail="You cannot remove your own admin role")
        if payload.is_active is False:
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    removing_admin = user.role == "admin" and (
        (payload.role is not None and payload.role != "admin") or payload.is_active is False
    )
    if removing_admin and _active_admin_count(db, exclude_user_id=user.id) == 0:
        raise HTTPException(status_code=400, detail="At least one active admin must remain")

    changes = {}
    if payload.full_name is not None:
        user.full_name = payload.full_name
        changes["full_name"] = payload.full_name
    if payload.email is not None:
        if db.query(User).filter(User.email == payload.email, User.id != user_id).first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = payload.email
        changes["email"] = payload.email
    new_role = payload.role if payload.role is not None else user.role
    if payload.role is not None and payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="Role must be admin, client or user")
    if user.role == "client" and new_role != "client" and db.query(User.id).filter(User.client_id == user.id).first():
        raise HTTPException(status_code=400, detail="This client still has users — move or deactivate them first")
    if payload.role is not None or payload.client_id is not None:
        client_id = _valid_client_id(db, new_role, payload.client_id if payload.client_id is not None else user.client_id)
        if client_id == user.id:
            raise HTTPException(status_code=422, detail="A user cannot belong to itself")
        if user.client_id != client_id:
            user.client_id = changes["client_id"] = client_id
        if user.role != new_role:
            user.role = changes["role"] = new_role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active
        if not payload.is_active and user.role == "client":
            # Its users can no longer sign in either; end their sessions now.
            member_ids = [row.id for row in db.query(User.id).filter(User.client_id == user.id)]
            if member_ids:
                db.query(UserSession).filter(UserSession.user_id.in_(member_ids), UserSession.is_active == True).update(
                    {"is_active": False, "revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
    if payload.new_password:
        validate_password_strength(payload.new_password)
        user.hashed_password = hash_password(payload.new_password)
        # Revoke all sessions on password reset
        db.query(UserSession).filter(
            UserSession.user_id == user_id, UserSession.is_active == True
        ).update({"is_active": False, "revoked_at": datetime.now(timezone.utc)})
        changes["password"] = "reset"
    if payload.reset_mfa and user.mfa_enabled:
        user.mfa_enabled = False
        user.mfa_secret = None
        user.mfa_recovery_codes = None
        user.mfa_last_used_step = None
        changes["mfa"] = "reset"

    db.commit()
    db.refresh(user)
    _log_audit(db, "user_updated", admin.id, "user", user.id,
               _get_ip(request), request.headers.get("User-Agent", ""),
               details=changes)
    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "admin" and user.is_active and _active_admin_count(db, exclude_user_id=user.id) == 0:
        raise HTTPException(status_code=400, detail="At least one active admin must remain")

    # Soft-delete: deactivate instead of hard delete to preserve audit trail.
    # A client's users lose access with it.
    user.is_active = False
    affected = [user_id] + ([row.id for row in db.query(User.id).filter(User.client_id == user.id)] if user.role == "client" else [])
    db.query(UserSession).filter(
        UserSession.user_id.in_(affected), UserSession.is_active == True
    ).update({"is_active": False, "revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    _log_audit(db, "user_deactivated", admin.id, "user", user_id,
               _get_ip(request), request.headers.get("User-Agent", ""),
               details={"deactivated_username": user.username})
    return {"message": f"User '{user.username}' deactivated"}


# ── System stats ──────────────────────────────────────────────

@router.get("/system-stats")
def system_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    total_users    = db.query(func.count(User.id)).scalar() or 0
    active_users   = db.query(func.count(User.id)).filter(User.is_active == True).scalar() or 0
    admin_users    = db.query(func.count(User.id)).filter(User.role == "admin", User.is_active == True).scalar() or 0
    active_sessions = db.query(func.count(UserSession.id)).filter(UserSession.is_active == True).scalar() or 0
    total_emails   = db.query(func.count(EmailBatch.id)).scalar() or 0
    finished       = db.query(func.count(EmailBatch.id)).filter(
        EmailBatch.status.in_(("SUCCESS", "REJECTED", "FAILED", "IGNORED"))
    ).scalar() or 0
    replies_sent   = db.query(func.count(EmailBatchEvent.id)).filter(EmailBatchEvent.reply_sent == True).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "admins": admin_users,
            "clients": active_users - admin_users,
        },
        "sessions": {"active": active_sessions},
        "emails": {
            "total": total_emails,
            "processed": finished,
            "unprocessed": total_emails - finished,
        },
        "replies": {"sent": replies_sent},
    }


# ── User activity summary ─────────────────────────────────────

@router.get("/users/{user_id}/activity")
def user_activity(
    user_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    logs = (
        db.query(AuditLog)
        .filter(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "user": {"id": user.id, "username": user.username, "role": user.role},
        "activity": [
            {
                "id": l.id,
                "action": l.action,
                "resource_type": l.resource_type,
                "resource_id": l.resource_id,
                "status": l.status,
                "ip_address": l.ip_address,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in logs
        ],
    }


# ── Background jobs: dead-letter queue ────────────────────────

@router.get("/jobs/failed")
def list_failed_jobs(
    status: str = Query("failed", pattern="^(failed|retried|discarded|all)$"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from app.models.user import FailedJob

    q = db.query(FailedJob)
    if status != "all":
        q = q.filter(FailedJob.status == status)
    rows = q.order_by(FailedJob.created_at.desc(), FailedJob.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id, "job_name": r.job_name, "args": r.args_json, "job_key": r.job_key,
            "attempts": r.attempts, "error": r.error, "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        }
        for r in rows
    ]


@router.post("/jobs/failed/{failed_job_id}/retry")
async def retry_failed_job(
    failed_job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Re-queue a dead-lettered job with a fresh retry budget."""
    from app.jobs.queue import REGISTRY, enqueue, mark_resolved
    from app.models.user import FailedJob

    row = db.query(FailedJob).filter(FailedJob.id == failed_job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Failed job not found")
    if row.status != "failed":
        raise HTTPException(status_code=409, detail=f"Job is already {row.status}")
    if row.job_name not in REGISTRY:
        raise HTTPException(status_code=422, detail=f"Unknown job '{row.job_name}'")
    mark_resolved(row.id, "retried")
    result = await enqueue(row.job_name, *(row.args_json or []), job_id=f"retry:{row.id}")
    _log_audit(db, "job_retried", admin.id, "failed_job", row.id,
               _get_ip(request), request.headers.get("User-Agent", ""), details={"job": row.job_name})
    return {"message": f"Job {row.job_name} re-queued", "result": result}


@router.post("/jobs/failed/{failed_job_id}/discard")
def discard_failed_job(
    failed_job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from app.jobs.queue import mark_resolved
    from app.models.user import FailedJob

    row = db.query(FailedJob).filter(FailedJob.id == failed_job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Failed job not found")
    mark_resolved(row.id, "discarded")
    _log_audit(db, "job_discarded", admin.id, "failed_job", row.id,
               _get_ip(request), request.headers.get("User-Agent", ""), details={"job": row.job_name})
    return {"message": "Job discarded"}


# ── Ops alerts ────────────────────────────────────────────────

@router.post("/ops-alert/test")
async def test_ops_alert(admin: User = Depends(require_admin)):
    """Send a test message to OPS_ALERT_WEBHOOK_URL so admins can check the channel."""
    import asyncio
    from app.config import settings
    from app.services.ops_alert import send_ops_alert

    if not settings.OPS_ALERT_WEBHOOK_URL:
        raise HTTPException(status_code=400, detail="OPS_ALERT_WEBHOOK_URL is not set in backend/.env")
    delivered = await asyncio.to_thread(
        send_ops_alert, "Test alert from MailAI",
        f"Alerts are working. Sent by {admin.username}. You will be told here when an email needs attention "
        "or a mailbox stops working.",
    )
    if not delivered:
        raise HTTPException(status_code=502, detail="The webhook did not accept the alert; check the URL")
    return {"message": "Test alert sent"}
