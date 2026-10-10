"""Team: a client manages the user (staff) logins of its own account."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserSession
from app.routers.auth import _get_ip, _log_audit, get_current_user, hash_password, validate_password_strength
from app.schemas.user import UserOut

router = APIRouter()


def require_client(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "client":
        raise HTTPException(status_code=403, detail="Only a client account can manage its team")
    return current_user


class TeamUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=255)
    password: str


class TeamUserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = None


def _member(db: Session, client: User, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id, User.role == "user", User.client_id == client.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found in your team")
    return user


def _revoke_sessions(db: Session, user_id: int) -> None:
    db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.is_active == True).update(  # noqa: E712
        {"is_active": False, "revoked_at": datetime.now(timezone.utc)})


@router.get("", response_model=list[UserOut])
def list_team(db: Session = Depends(get_db), client: User = Depends(require_client)):
    return db.query(User).filter(User.role == "user", User.client_id == client.id).order_by(User.created_at.desc()).all()


@router.post("", response_model=UserOut, status_code=201)
def add_team_user(payload: TeamUserCreate, request: Request, db: Session = Depends(get_db),
                  client: User = Depends(require_client)):
    if db.query(User.id).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User.id).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    validate_password_strength(payload.password)
    user = User(username=payload.username, email=payload.email, full_name=payload.full_name,
                hashed_password=hash_password(payload.password), role="user", client_id=client.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    _log_audit(db, "team_user_created", client.id, "user", user.id, _get_ip(request),
               request.headers.get("User-Agent", ""), details={"created_username": user.username})
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_team_user(user_id: int, payload: TeamUserUpdate, request: Request, db: Session = Depends(get_db),
                     client: User = Depends(require_client)):
    user = _member(db, client, user_id)
    changes: dict = {}
    if payload.full_name is not None:
        user.full_name = changes["full_name"] = payload.full_name
    if payload.email is not None:
        if db.query(User.id).filter(User.email == payload.email, User.id != user.id).first():
            raise HTTPException(status_code=409, detail="Email already in use")
        user.email = changes["email"] = payload.email
    if payload.is_active is not None:
        user.is_active = changes["is_active"] = payload.is_active
        if not payload.is_active:
            _revoke_sessions(db, user.id)
    if payload.new_password:
        validate_password_strength(payload.new_password)
        user.hashed_password = hash_password(payload.new_password)
        _revoke_sessions(db, user.id)
        changes["password"] = "reset"
    db.commit()
    db.refresh(user)
    _log_audit(db, "team_user_updated", client.id, "user", user.id, _get_ip(request),
               request.headers.get("User-Agent", ""), details=changes)
    return user


@router.delete("/{user_id}")
def remove_team_user(user_id: int, request: Request, db: Session = Depends(get_db),
                     client: User = Depends(require_client)):
    """Deactivate (not hard-delete) so the audit trail stays."""
    user = _member(db, client, user_id)
    user.is_active = False
    _revoke_sessions(db, user.id)
    db.commit()
    _log_audit(db, "team_user_deactivated", client.id, "user", user.id, _get_ip(request),
               request.headers.get("User-Agent", ""), details={"deactivated_username": user.username})
    return {"message": f"User '{user.username}' deactivated"}
