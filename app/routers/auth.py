"""
Auth router — login, logout, refresh tokens, registration, password change.
Includes account lockout after repeated failures and full session tracking.
"""
from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import bcrypt
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

from app.database import get_db
from app.models.user import User, UserSession, AuditLog
from app.config import settings
from app.schemas.user import TokenResponse, UserOut

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES     = 15
REFRESH_TOKEN_DAYS  = 7


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        try:
            return pwd_context.verify(plain, hashed)
        except Exception:
            return False


def hash_password(password: str) -> str:
    try:
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")
    except Exception:
        return pwd_context.hash(password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    to_encode["type"] = "access"
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _log_audit(db, action, user_id=None, resource_type=None, resource_id=None,
               ip_address=None, user_agent=None, status="success", details=None):
    db.add(AuditLog(
        user_id=user_id, action=action, resource_type=resource_type,
        resource_id=resource_id, ip_address=ip_address, user_agent=user_agent,
        status=status, details=details,
    ))
    db.commit()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "access":
            raise credentials_exception
        user_id_raw = payload.get("sub")
        user_id = int(user_id_raw) if user_id_raw is not None else None
        if user_id is None:
            raise credentials_exception
    except (JWTError, ValueError, TypeError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise credentials_exception

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account temporarily locked — too many failed attempts",
        )
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    full_name: str | None = None
    password: str
    role: str = "employee"


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login", response_model=TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    ip  = _get_ip(request)
    ua  = request.headers.get("User-Agent", "")
    now = datetime.now(timezone.utc)

    user = db.query(User).filter(User.username == form_data.username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password")

    if user.locked_until and user.locked_until > now:
        mins_left = int((user.locked_until - now).total_seconds() / 60) + 1
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Account locked — try again in {mins_left} minute(s)")

    if not verify_password(form_data.password, user.hashed_password):
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            db.commit()
            _log_audit(db, "login_locked", user.id, "user", user.id, ip, ua, "failure",
                       {"reason": "max_failed_attempts"})
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Account locked for {LOCKOUT_MINUTES} minutes")
        db.commit()
        _log_audit(db, "login_failed", user.id, "user", user.id, ip, ua, "failure",
                   {"attempt": user.failed_login_count})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    user.failed_login_count = 0
    user.locked_until       = None
    user.last_login_at      = now

    access_token  = create_access_token({"sub": str(user.id), "role": user.role})
    refresh_token = create_refresh_token()

    existing_session = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id)
        .first()
    )
    if existing_session:
        existing_session.refresh_token = refresh_token
        existing_session.ip_address = ip
        existing_session.user_agent = ua
        existing_session.is_active = True
        existing_session.expires_at = now + timedelta(days=REFRESH_TOKEN_DAYS)
        existing_session.last_used_at = now
        existing_session.revoked_at = None
    else:
        db.add(UserSession(
            user_id=user.id, refresh_token=refresh_token,
            ip_address=ip, user_agent=ua,
            expires_at=now + timedelta(days=REFRESH_TOKEN_DAYS),
            last_used_at=now,
        ))
    db.commit()
    _log_audit(db, "login", user.id, "user", user.id, ip, ua)

    return TokenResponse(
        access_token=access_token, refresh_token=refresh_token,
        token_type="bearer", role=user.role,
        username=user.username, full_name=user.full_name, user_id=user.id,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token_endpoint(
    request: Request,
    payload: RefreshRequest,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    session = (
        db.query(UserSession)
        .filter(UserSession.refresh_token == payload.refresh_token,
                UserSession.is_active == True)
        .first()
    )
    if not session or session.expires_at < now:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    new_refresh = create_refresh_token()
    session.refresh_token = new_refresh
    session.ip_address = _get_ip(request)
    session.user_agent = request.headers.get("User-Agent", "")
    session.is_active = True
    session.expires_at = now + timedelta(days=REFRESH_TOKEN_DAYS)
    session.last_used_at = now
    session.revoked_at = None
    db.commit()

    return TokenResponse(
        access_token=create_access_token({"sub": str(user.id), "role": user.role}),
        refresh_token=new_refresh, token_type="bearer",
        role=user.role, username=user.username,
        full_name=user.full_name, user_id=user.id,
    )


@router.post("/logout")
def logout(
    request: Request,
    payload: RefreshRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.now(timezone.utc)
    session = (
        db.query(UserSession)
        .filter(UserSession.refresh_token == payload.refresh_token,
                UserSession.user_id == current_user.id)
        .first()
    )
    if session:
        session.is_active  = False
        session.revoked_at = now
        db.commit()
    _log_audit(db, "logout", current_user.id, "user", current_user.id,
               _get_ip(request), request.headers.get("User-Agent", ""))
    return {"message": "Logged out successfully"}


@router.post("/register", response_model=UserOut, status_code=201)
def register(
    request: Request,
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if payload.role not in ("admin", "client"):
        raise HTTPException(status_code=422, detail="role must be 'admin' or 'client'")

    user = User(
        username=payload.username, email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _log_audit(db, "user_created", admin.id, "user", user.id,
               _get_ip(request), request.headers.get("User-Agent", ""),
               details={"created_username": payload.username, "role": payload.role})
    return user


@router.post("/change-password")
def change_password(
    request: Request,
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        _log_audit(db, "password_change_failed", current_user.id, "user", current_user.id,
                   _get_ip(request), request.headers.get("User-Agent", ""), "failure")
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    current_user.hashed_password = hash_password(payload.new_password)
    db.query(UserSession).filter(
        UserSession.user_id == current_user.id,
        UserSession.is_active == True,
    ).update({"is_active": False, "revoked_at": datetime.now(timezone.utc)})
    db.commit()
    _log_audit(db, "password_changed", current_user.id, "user", current_user.id,
               _get_ip(request), request.headers.get("User-Agent", ""))
    return {"message": "Password changed. Please log in again."}


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/sessions")
def list_my_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sessions = (
        db.query(UserSession)
        .filter(UserSession.user_id == current_user.id, UserSession.is_active == True)
        .order_by(UserSession.created_at.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
        }
        for s in sessions
    ]


@router.delete("/sessions/{session_id}")
def revoke_session(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(UserSession).filter(UserSession.id == session_id)
    if current_user.role != "admin":
        q = q.filter(UserSession.user_id == current_user.id)
    session = q.first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    session.is_active  = False
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    _log_audit(db, "session_revoked", current_user.id, "user", session.user_id,
               _get_ip(request), request.headers.get("User-Agent", ""),
               details={"session_id": session_id})
    return {"message": "Session revoked"}
