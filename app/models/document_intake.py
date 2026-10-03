"""
Email intake models: one batch per inbound email, its attachments and its audit trail.

Status flow:  RECEIVED -> PROCESSING -> SUCCESS | REJECTED | FAILED
  REJECTED = a rule failed and the sender was told why (domain, no attachment,
             unsupported type, unreadable/protected attachment).
  FAILED   = a system problem (converter missing, storage error); the sender is
             not blamed and an admin can reprocess the email.
"""
from sqlalchemy import (
    Column, String, Text, Boolean, ForeignKey,
    Integer, JSON, Numeric, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, false
from app.database import Base, UTCDateTime


class EmailBatch(Base):
    """One row per inbound email."""
    __tablename__ = "email_batches"
    __table_args__ = (
        UniqueConstraint("integration_id", "message_id", name="uq_email_batches_integration_message"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    batch_no          = Column(String(60), unique=True, nullable=False, index=True)
    message_id        = Column(String(512), nullable=False, index=True)
    conversation_id   = Column(String(512))     # provider message id, used to re-fetch for reprocessing
    integration_id    = Column(Integer, ForeignKey("email_integrations.id", ondelete="SET NULL"), nullable=True)
    mailbox_type      = Column(String(10))      # PROD | UAT | DEV
    sender_name       = Column(String(255))
    sender_email      = Column(String(255), nullable=False)
    recipient_email   = Column(String(255))
    subject           = Column(Text)
    body_text         = Column(Text)
    received_datetime = Column(UTCDateTime(), nullable=False)
    status            = Column(String(30), default="RECEIVED", index=True)
    # Which rule decided the result, e.g. DOMAIN_NOT_ALLOWED, NO_ATTACHMENT, PROCESSED
    outcome           = Column(String(40), index=True)
    status_reason     = Column(Text)
    attachment_count  = Column(Integer, default=0)
    email_pdf_path    = Column(Text)            # PDF of the email content (rule 5.2)
    merged_pdf_path   = Column(Text)            # attachments + email PDF last (rule 5.3/5.4)

    # AI analysis, run for every email as soon as it is picked up
    sentiment          = Column(String(20))     # positive | neutral | negative
    sentiment_score    = Column(Numeric(5, 4))
    primary_emotion    = Column(String(50))
    email_category     = Column(String(50))
    priority           = Column(String(20), index=True)   # critical | high | medium | low
    ai_summary         = Column(Text)
    ai_model_version   = Column(String(50))

    processed_at = Column(UTCDateTime())
    # Retention: after the mailbox's retention period the stored PDFs are deleted;
    # the record, its timeline and attachment statuses are kept.
    is_archived  = Column(Boolean, default=False, server_default=false(), index=True)
    archived_at  = Column(UTCDateTime())
    created_at   = Column(UTCDateTime(), server_default=func.now())
    updated_at   = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())

    integration = relationship("EmailIntegration")
    events      = relationship("EmailBatchEvent", back_populates="batch", cascade="all, delete-orphan")
    attachments = relationship("EmailBatchAttachment", back_populates="batch", cascade="all, delete-orphan")


class EmailBatchEvent(Base):
    """Audit trail — one row per step/decision/reply for an email."""
    __tablename__ = "email_batch_events"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    parent_batch_id  = Column(Integer, ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False)
    batch_no         = Column(String(60), index=True)
    event_type       = Column(String(40), nullable=False)
    related_filename = Column(String(255))
    reply_sent       = Column(Boolean, default=False)
    reply_message_id = Column(String(512))
    details          = Column(JSON, default=dict)
    created_at       = Column(UTCDateTime(), server_default=func.now())

    batch = relationship("EmailBatch", back_populates="events")


class EmailBatchAttachment(Base):
    """One row per attachment of an email."""
    __tablename__ = "email_batch_attachments"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    parent_batch_id        = Column(Integer, ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False)
    batch_no               = Column(String(60), index=True)
    batch_source_filename  = Column(String(255), nullable=False)
    doc_type               = Column(String(20))
    file_size_bytes        = Column(Integer)
    received_date          = Column(UTCDateTime())
    is_encrypted           = Column(Boolean, default=False)
    converted_pdf_path     = Column(Text)       # this file as a PDF (rule 5.1)
    status                 = Column(String(20), default="PENDING")
    # PENDING | INVALID_TYPE | PROTECTED | UNREADABLE | CONVERTED | MERGED | FAILED
    status_reason          = Column(Text)
    created_at             = Column(UTCDateTime(), server_default=func.now())

    batch = relationship("EmailBatch", back_populates="attachments")


class BatchSequence(Base):
    """Concurrency-safe per-prefix/day sequence counter for batch numbering."""
    __tablename__ = "batch_sequences"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    sequence_key  = Column(String(80), unique=True, nullable=False, index=True)  # e.g. "CLM-PROD-20260905"
    last_value    = Column(Integer, nullable=False, default=0)
    updated_at    = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class EmailTemplate(Base):
    """Auto-reply text for each rule. ``integration_id=NULL`` rows are the global defaults."""
    __tablename__ = "email_templates"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    integration_id     = Column(Integer, ForeignKey("email_integrations.id", ondelete="CASCADE"), nullable=True, index=True)
    template_key       = Column(String(60), nullable=False, index=True)
    locale             = Column(String(10), default="en")
    subject_template   = Column(Text, nullable=False)
    html_body_template = Column(Text, nullable=False)
    signature_html     = Column(Text)
    logo_url           = Column(Text)
    is_active          = Column(Boolean, default=True)
    created_at         = Column(UTCDateTime(), server_default=func.now())
    updated_at         = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())

    integration = relationship("EmailIntegration")
