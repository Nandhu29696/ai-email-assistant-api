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
from app.models.email import Email, EmailAnalysis, EmailReply
from app.routers.auth import require_admin, hash_password, _log_audit, _get_ip
from app.schemas.user import UserOut

router = APIRouter()


class UserUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = None


# ── User management ───────────────────────────────────────────

@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    search: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
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
    if is_active is not None:
        q = q.filter(User.is_active == is_active)
    return q.order_by(User.created_at.desc()).all()


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

    changes = {}
    if payload.full_name is not None:
        user.full_name = payload.full_name
        changes["full_name"] = payload.full_name
    if payload.email is not None:
        if db.query(User).filter(User.email == payload.email, User.id != user_id).first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = payload.email
        changes["email"] = payload.email
    if payload.role is not None:
        if payload.role not in ("admin", "client"):
            raise HTTPException(status_code=422, detail="Role must be admin or client")
        user.role = payload.role
        changes["role"] = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active
    if payload.new_password:
        user.hashed_password = hash_password(payload.new_password)
        # Revoke all sessions on password reset
        db.query(UserSession).filter(
            UserSession.user_id == user_id, UserSession.is_active == True
        ).update({"is_active": False, "revoked_at": datetime.now(timezone.utc)})
        changes["password"] = "reset"

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

    # Soft-delete: deactivate instead of hard delete to preserve audit trail
    user.is_active = False
    db.query(UserSession).filter(
        UserSession.user_id == user_id, UserSession.is_active == True
    ).update({"is_active": False, "revoked_at": datetime.now(timezone.utc)})
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
    admin_users    = db.query(func.count(User.id)).filter(User.role == "admin").scalar() or 0
    active_sessions = db.query(func.count(UserSession.id)).filter(UserSession.is_active == True).scalar() or 0
    total_emails   = db.query(func.count(Email.id)).scalar() or 0
    processed      = db.query(func.count(Email.id)).filter(Email.processed_at.isnot(None)).scalar() or 0
    total_replies  = db.query(func.count(EmailReply.id)).scalar() or 0
    sent_replies   = db.query(func.count(EmailReply.id)).filter(EmailReply.is_draft == False).scalar() or 0

    return {
        "users": {
            "total": total_users,
            "active": active_users,
            "admins": admin_users,
            "employees": active_users - admin_users,
        },
        "sessions": {"active": active_sessions},
        "emails": {
            "total": total_emails,
            "processed": processed,
            "unprocessed": total_emails - processed,
        },
        "replies": {
            "total": total_replies,
            "sent": sent_replies,
            "drafts": total_replies - sent_replies,
        },
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
