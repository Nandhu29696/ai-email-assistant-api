from sqlalchemy import Column, String, Boolean, Integer, BigInteger, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import sqlalchemy as sa
from app.database import Base, UTCDateTime


class User(Base):
    __tablename__ = "users"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    email               = Column(String(255), unique=True, nullable=False, index=True)
    username            = Column(String(100), unique=True, nullable=False, index=True)
    full_name           = Column(String(255))
    hashed_password     = Column(String(255), nullable=False)
    role                = Column(String(20), nullable=False, default="client")
    is_active           = Column(Boolean, default=True)
    last_login_at       = Column(UTCDateTime())
    failed_login_count  = Column(Integer, default=0)
    locked_until        = Column(UTCDateTime())
    mfa_enabled         = Column(Boolean, nullable=False, default=False, server_default=sa.false())
    mfa_secret          = Column(Text)            # encrypted base32 TOTP secret
    mfa_recovery_codes  = Column(JSON)            # list of SHA-256 hashes of unused codes
    mfa_last_used_step  = Column(BigInteger)      # replay protection for TOTP codes
    created_at          = Column(UTCDateTime(), server_default=func.now())
    updated_at          = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())

    sessions   = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog",    back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    """Tracks refresh-token sessions per user (one row per device / login)."""
    __tablename__ = "user_sessions"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token = Column(String(512), unique=True, nullable=False, index=True)  # SHA-256 of the token
    ip_address    = Column(String(45))
    user_agent    = Column(String(512))
    is_active     = Column(Boolean, default=True)
    expires_at    = Column(UTCDateTime(), nullable=False)
    last_used_at  = Column(UTCDateTime())
    revoked_at    = Column(UTCDateTime())
    created_at    = Column(UTCDateTime(), server_default=func.now())

    user = relationship("User", back_populates="sessions")


class OAuthState(Base):
    """Single-use OAuth state records bound to the initiating user/provider."""
    __tablename__ = "oauth_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    state_hash = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)
    expires_at = Column(UTCDateTime(), nullable=False, index=True)
    used_at = Column(UTCDateTime())
    created_at = Column(UTCDateTime(), server_default=func.now())

    user = relationship("User")


class AuditLog(Base):
    """Immutable audit trail: who did what, when, from where."""
    __tablename__ = "audit_logs"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action        = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(50))
    resource_id   = Column(Integer)
    ip_address    = Column(String(45))
    user_agent    = Column(String(512))
    status        = Column(String(20), default="success")
    details       = Column(JSON)
    created_at    = Column(UTCDateTime(), server_default=func.now(), index=True)

    user = relationship("User", back_populates="audit_logs")


class FailedJob(Base):
    """Dead-letter queue: background jobs that exhausted their retries."""
    __tablename__ = "failed_jobs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    job_name    = Column(String(100), nullable=False, index=True)
    args_json   = Column(JSON)
    job_key     = Column(String(255))
    attempts    = Column(Integer, nullable=False, default=0)
    error       = Column(Text)
    status      = Column(String(20), nullable=False, default="failed", index=True)  # failed | retried | discarded
    created_at  = Column(UTCDateTime(), server_default=func.now(), index=True)
    resolved_at = Column(UTCDateTime())


class ApiRequestLog(Base):
    """Per-request log written by middleware."""
    __tablename__ = "api_request_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    user_id          = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    method           = Column(String(10))
    path             = Column(String(512), index=True)
    query_params     = Column(Text)
    status_code      = Column(Integer, index=True)
    response_time_ms = Column(Integer)
    ip_address       = Column(String(45))
    user_agent       = Column(String(512))
    error_detail     = Column(Text)
    created_at       = Column(UTCDateTime(), server_default=func.now(), index=True)
