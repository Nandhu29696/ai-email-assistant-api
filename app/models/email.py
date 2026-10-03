"""
Mailbox and sender-domain models.

Columns/tables of the retired conversation features (inbox, AI replies, review
queue, reply tracker, notifications, callbacks, retention) still exist in older
databases but are no longer mapped here. See FUTURE_ENHANCEMENTS.md.
"""
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base, UTCDateTime


class EmailIntegration(Base):
    """A connected mailbox. Every new email in it runs through the intake rules."""
    __tablename__ = "email_integrations"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    provider      = Column(String(20), nullable=False)      # gmail | outlook | imap
    email_address = Column(String(255), nullable=False, unique=True)
    access_token  = Column(Text)
    refresh_token = Column(Text)
    token_expiry  = Column(UTCDateTime())
    is_active     = Column(Boolean, default=True)
    created_at    = Column(UTCDateTime(), server_default=func.now())
    updated_at    = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())
    last_sync_at  = Column(UTCDateTime())
    last_email_processed_at = Column(UTCDateTime())
    health_status = Column(String(20), default="unknown")  # healthy | degraded | error | unknown
    health_message = Column(Text)

    # Only emails received at or after this moment are processed, so connecting
    # (or re-connecting) a mailbox never auto-replies to its old backlog.
    process_since = Column(UTCDateTime())

    # ── Intake rules (sensible defaults; nothing has to be configured) ──
    batch_prefix         = Column(String(10))
    mailbox_type         = Column(String(10), default="PROD")   # PROD | UAT | DEV
    allowed_extensions   = Column(String(100), default="pdf,doc,docx,tiff,tif")
    max_file_size_mb     = Column(Integer, default=25)
    allowed_sender_domains = Column(Text)   # comma-separated; empty = use the global allowed-domain list
    success_folder_label = Column(String(100), default="Processed/Success")
    failed_folder_label  = Column(String(100), default="Processed/Failed")
    retention_days       = Column(Integer, default=90)   # stored PDFs are deleted after this many days

    # ── Provider sync state ──
    outlook_subscription_id         = Column(String(255))
    outlook_subscription_expires_at = Column(UTCDateTime())
    gmail_history_id       = Column(String(40))
    gmail_watch_expires_at = Column(UTCDateTime())
    # Per-mailbox IMAP/SMTP credentials (passwords encrypted)
    imap_host     = Column(String(255))
    imap_port     = Column(Integer)
    imap_username = Column(String(255))
    imap_password = Column(Text)
    smtp_host     = Column(String(255))
    smtp_port     = Column(Integer)
    smtp_username = Column(String(255))
    smtp_password = Column(Text)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    owner_user = relationship("User", foreign_keys=[owner_user_id])


class AllowedDomain(Base):
    """Global sender-domain allow-list (rule 1). A mailbox may override it."""
    __tablename__ = "allowed_domains"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    domain     = Column(String(255), unique=True, nullable=False)  # e.g. "example.com"
    is_active  = Column(Boolean, default=True, nullable=False)
    notes      = Column(String(500))
    created_at = Column(UTCDateTime(), server_default=func.now())
