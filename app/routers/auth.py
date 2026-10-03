"""
Auth router — login (with optional TOTP MFA), logout, refresh, registration,
password change and session management.

Browsers authenticate with httpOnly cookies (access + refresh) plus a CSRF
double-submit token; API clients may still send ``Authorization: Bearer``.
Includes account lockout after repeated failures and full session tracking.
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
from app.services import mfa as totp
from app.utils.crypto import decrypt_token, encrypt_token

router = APIRouter()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

ACCESS_COOKIE = "ea_access"
REFRESH_COOKIE = "ea_refresh"
CSRF_COOKIE = "ea_csrf"
CSRF_HEADER = "X-CSRF-Token"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MFA_TOKEN_MINUTES = 5

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES     = 15
REFRESH_TOKEN_DAYS  = 7
MAX_SESSIONS_PER_USER = 10
VALID_ROLES = ("admin", "client")

# Pre-computed hash so unknown usernames cost the same bcrypt time as real ones.
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"timing-equaliser", bcrypt.gensalt()).decode("utf-8")

# Simple per-process sliding-window limiter for the login endpoint.
_login_attempts: dict[str, deque] = defaultdict(deque)
_login_lock = threading.Lock()


def _check_login_rate_limit(ip: str) -> None:
    limit = settings.LOGIN_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return
    now = time.monotonic()
    with _login_lock:
        attempts = _login_attempts[ip]
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= limit:
            raise HTTPException(status_code=429, detail="Too many login attempts. Please wait a minute.")
        attempts.append(now)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_password_strength(password: str) -> None:
    """Reject weak passwords (length + character variety)."""
    problems = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"at least {settings.PASSWORD_MIN_LENGTH} characters")
    if not any(c.isalpha() for c in password):
        problems.append("a letter")
    if not any(c.isdigit() for c in password):
        problems.append("a digit")
    if problems:
        raise HTTPException(status_code=422, detail="Password must contain " + ", ".join(problems))


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


def _cookie_kwargs(path: str = "/") -> dict:
    return {
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.AUTH_COOKIE_SAMESITE.lower(),
        "domain": settings.AUTH_COOKIE_DOMAIN or None,
        "path": path,
    }


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """httpOnly access/refresh cookies + a readable CSRF token for double-submit."""
    response.set_cookie(
        ACCESS_COOKIE, access_token, httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, **_cookie_kwargs(),
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh_token, httponly=True,
        max_age=REFRESH_TOKEN_DAYS * 86400, **_cookie_kwargs("/api/auth"),
    )
    response.set_cookie(
        CSRF_COOKIE, secrets.token_urlsafe(32), httponly=False,
        max_age=REFRESH_TOKEN_DAYS * 86400, **_cookie_kwargs(),
    )


def clear_auth_cookies(response: Response) -> None:
    for name, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, "/api/auth"), (CSRF_COOKIE, "/")):
        kwargs = _cookie_kwargs(path)
        response.delete_cookie(name, path=path, domain=kwargs["domain"], secure=kwargs["secure"],
                               samesite=kwargs["samesite"])


def _wants_tokens_in_body(request: Request) -> bool:
    """Non-browser API clients opt in to receiving tokens in the JSON body."""
    return request.headers.get("X-Auth-Mode", "").lower() == "token"


def verify_csrf(request: Request) -> None:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")


def _user_from_access_token(token: str, db: Session) -> User:
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


def get_current_user(
    request: Request,
    bearer_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate via ``Authorization: Bearer`` or the httpOnly access cookie.

    Cookie-authenticated state-changing requests must carry the CSRF header.
    """
    token = bearer_token
    if not token:
        token = request.cookies.get(ACCESS_COOKIE)
        if token and request.method not in _SAFE_METHODS:
            verify_csrf(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _user_from_access_token(token, db)


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    full_name: str | None = None
    password: str
    role: str = "client"


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


def _record_failed_attempt(db: Session, user: User, now: datetime, ip: str, ua: str, reason: str) -> None:
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
               {"attempt": user.failed_login_count, "reason": reason})


def _check_not_locked(db: Session, user: User, now: datetime) -> None:
    if user.locked_until and user.locked_until > now:
        mins_left = int((user.locked_until - now).total_seconds() / 60) + 1
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Account locked — try again in {mins_left} minute(s)")
    if user.locked_until and user.locked_until <= now:
        # Lock expired: start counting failures afresh.
        user.locked_until = None
        user.failed_login_count = 0


def _issue_session(
    db: Session, request: Request, response: Response, user: User, now: datetime, ip: str, ua: str,
) -> TokenResponse:
    user.failed_login_count = 0
    user.locked_until       = None
    user.last_login_at      = now

    access_token  = create_access_token({"sub": str(user.id), "role": user.role})
    refresh_token = create_refresh_token()

    db.add(UserSession(
        user_id=user.id, refresh_token=hash_refresh_token(refresh_token),
        ip_address=ip[:45], user_agent=ua,
        expires_at=now + timedelta(days=REFRESH_TOKEN_DAYS),
        last_used_at=now,
    ))
    db.flush()

    # Cap concurrent sessions per user; revoke the oldest beyond the limit.
    active = (
        db.query(UserSession)
        .filter(UserSession.user_id == user.id, UserSession.is_active == True)
        .order_by(UserSession.id.desc())
        .all()
    )
    for old_session in active[MAX_SESSIONS_PER_USER:]:
        old_session.is_active = False
        old_session.revoked_at = now
    db.commit()
    _log_audit(db, "login", user.id, "user", user.id, ip, ua, details={"mfa": bool(user.mfa_enabled)})

    set_auth_cookies(response, access_token, refresh_token)
    in_body = _wants_tokens_in_body(request)
    return TokenResponse(
        access_token=access_token if in_body else None,
        refresh_token=refresh_token if in_body else None,
        token_type="bearer", role=user.role,
        username=user.username, full_name=user.full_name, user_id=user.id,
        mfa_enabled=bool(user.mfa_enabled),
    )


def _create_mfa_token(user: User) -> str:
    return jwt.encode(
        {"sub": str(user.id), "type": "mfa",
         "exp": datetime.now(timezone.utc) + timedelta(minutes=MFA_TOKEN_MINUTES)},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM,
    )


@router.post("/login", response_model=TokenResponse, response_model_exclude_none=True)
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    ip  = _get_ip(request)
    ua  = request.headers.get("User-Agent", "")[:512]
    now = datetime.now(timezone.utc)
    _check_login_rate_limit(ip)

    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Incorrect username or password")

    user = db.query(User).filter(User.username == form_data.username).first()
    if not user:
        verify_password(form_data.password, _DUMMY_PASSWORD_HASH)
        raise invalid

    _check_not_locked(db, user, now)

    if not verify_password(form_data.password, user.hashed_password):
        _record_failed_attempt(db, user, now, ip, ua, "password")
        raise invalid

    if not user.is_active:
        raise invalid

    if user.mfa_enabled:
        # Second step required: POST /api/auth/mfa/verify with this token + a code.
        return TokenResponse(
            mfa_required=True, mfa_token=_create_mfa_token(user),
            role=user.role, username=user.username, full_name=user.full_name, user_id=user.id,
        )

    return _issue_session(db, request, response, user, now, ip, ua)


class MfaLoginRequest(BaseModel):
    mfa_token: str
    code: str


@router.post("/mfa/verify", response_model=TokenResponse, response_model_exclude_none=True)
def mfa_verify(
    request: Request,
    response: Response,
    payload: MfaLoginRequest,
    db: Session = Depends(get_db),
):
    """Complete a login for an account with MFA using a TOTP or recovery code."""
    ip = _get_ip(request)
    ua = request.headers.get("User-Agent", "")[:512]
    now = datetime.now(timezone.utc)
    _check_login_rate_limit(ip)
    try:
        claims = jwt.decode(payload.mfa_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if claims.get("type") != "mfa":
            raise ValueError("wrong token type")
        user_id = int(claims["sub"])
    except (JWTError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="MFA session expired — please sign in again")

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user or not user.mfa_enabled or not user.mfa_secret:
        raise HTTPException(status_code=401, detail="MFA session expired — please sign in again")
    _check_not_locked(db, user, now)

    if not _consume_mfa_code(user, payload.code):
        _record_failed_attempt(db, user, now, ip, ua, "mfa")
        raise HTTPException(status_code=401, detail="Invalid authentication code")
    return _issue_session(db, request, response, user, now, ip, ua)


def _consume_mfa_code(user: User, code: str) -> bool:
    """Accept a TOTP code (with replay protection) or a single-use recovery code."""
    secret = decrypt_token(user.mfa_secret) if user.mfa_secret else None
    if secret:
        step = totp.verify_totp(secret, code, user.mfa_last_used_step)
        if step is not None:
            user.mfa_last_used_step = step
            return True
    remaining = totp.consume_recovery_code(user.mfa_recovery_codes, code)
    if remaining is not None:
        user.mfa_recovery_codes = remaining
        return True
    return False


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True)
def refresh_token_endpoint(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """Rotate the refresh token (from the httpOnly cookie, or the body for API clients)."""
    now = datetime.now(timezone.utc)
    presented = (payload.refresh_token if payload and payload.refresh_token else None) or request.cookies.get(REFRESH_COOKIE)
    if not presented:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    session = (
        db.query(UserSession)
        .filter(UserSession.refresh_token == hash_refresh_token(presented),
                UserSession.is_active == True)
        .first()
    )
    if not session or session.expires_at < now:
        clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or disabled")

    new_refresh = create_refresh_token()
    session.refresh_token = hash_refresh_token(new_refresh)
    session.ip_address = _get_ip(request)[:45]
    session.user_agent = request.headers.get("User-Agent", "")[:512]
    session.expires_at = now + timedelta(days=REFRESH_TOKEN_DAYS)
    session.last_used_at = now
    db.commit()

    access_token = create_access_token({"sub": str(user.id), "role": user.role})
    set_auth_cookies(response, access_token, new_refresh)
    in_body = _wants_tokens_in_body(request)
    return TokenResponse(
        access_token=access_token if in_body else None,
        refresh_token=new_refresh if in_body else None, token_type="bearer",
        role=user.role, username=user.username,
        full_name=user.full_name, user_id=user.id, mfa_enabled=bool(user.mfa_enabled),
    )


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """Revoke the current session (identified by its refresh token) and clear auth cookies.

    Works even when the access token has already expired.
    """
    presented = (payload.refresh_token if payload and payload.refresh_token else None) or request.cookies.get(REFRESH_COOKIE)
    if request.cookies.get(ACCESS_COOKIE) or request.cookies.get(REFRESH_COOKIE):
        verify_csrf(request)
    now = datetime.now(timezone.utc)
    if presented:
        session = (
            db.query(UserSession)
            .filter(UserSession.refresh_token == hash_refresh_token(presented))
            .first()
        )
        if session:
            session.is_active  = False
            session.revoked_at = now
            db.commit()
            _log_audit(db, "logout", session.user_id, "user", session.user_id,
                       _get_ip(request), request.headers.get("User-Agent", ""))
    clear_auth_cookies(response)
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
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail="role must be 'admin' or 'client'")
    validate_password_strength(payload.password)

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
    validate_password_strength(payload.new_password)

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


# ── MFA management ────────────────────────────────────────────
class MfaCodeRequest(BaseModel):
    code: str


class MfaDisableRequest(BaseModel):
    password: str
    code: str


@router.get("/mfa/status")
def mfa_status(current_user: User = Depends(get_current_user)):
    return {
        "enabled": bool(current_user.mfa_enabled),
        "recovery_codes_remaining": len(current_user.mfa_recovery_codes or []),
    }


@router.post("/mfa/setup")
def mfa_setup(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a new (not yet active) TOTP secret for the authenticator app."""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled; disable it first to re-enroll")
    secret = totp.generate_secret()
    current_user.mfa_secret = encrypt_token(secret)
    current_user.mfa_last_used_step = None
    db.commit()
    return {
        "secret": secret,
        "otpauth_uri": totp.provisioning_uri(secret, current_user.email or current_user.username, settings.MFA_ISSUER),
    }


@router.post("/mfa/enable")
def mfa_enable(
    request: Request,
    payload: MfaCodeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Confirm enrollment with a code from the app; returns one-time recovery codes."""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is already enabled")
    secret = decrypt_token(current_user.mfa_secret) if current_user.mfa_secret else None
    step = totp.verify_totp(secret, payload.code) if secret else None
    if step is None:
        raise HTTPException(status_code=400, detail="Invalid code — check the time on your device and try again")
    codes, hashes = totp.generate_recovery_codes()
    current_user.mfa_enabled = True
    current_user.mfa_last_used_step = step
    current_user.mfa_recovery_codes = hashes
    db.commit()
    _log_audit(db, "mfa_enabled", current_user.id, "user", current_user.id,
               _get_ip(request), request.headers.get("User-Agent", ""))
    return {"message": "MFA enabled", "recovery_codes": codes}


@router.post("/mfa/disable")
def mfa_disable(
    request: Request,
    payload: MfaDisableRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    if not verify_password(payload.password, current_user.hashed_password) or not _consume_mfa_code(current_user, payload.code):
        raise HTTPException(status_code=400, detail="Password or code is incorrect")
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_recovery_codes = None
    current_user.mfa_last_used_step = None
    db.commit()
    _log_audit(db, "mfa_disabled", current_user.id, "user", current_user.id,
               _get_ip(request), request.headers.get("User-Agent", ""))
    return {"message": "MFA disabled"}
