"""
Document Intake & Batch Processing Pipeline — SQLAlchemy models.
See DOCUMENT_INTAKE_BATCH_PROCESSING_PLAN.md for full design (§3).
"""
from sqlalchemy import (
    Column, String, Text, Boolean, DateTime, ForeignKey,
    Integer, SmallInteger, JSON, Numeric, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class EmailBatch(Base):
    """Parent table — one row per inbound document-intake email (§3.2)."""
    __tablename__ = "email_batches"
    __table_args__ = (
        UniqueConstraint("integration_id", "message_id", name="uq_email_batches_integration_message"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    batch_no          = Column(String(60), unique=True, nullable=False, index=True)
    message_id        = Column(String(512), nullable=False, index=True)
    conversation_id   = Column(String(512))
    integration_id    = Column(Integer, ForeignKey("email_integrations.id", ondelete="SET NULL"), nullable=True)
    mailbox_type      = Column(String(10))          # PROD | UAT | DEV
    email_type        = Column(String(30), default="inbound_document")
    sender_email      = Column(String(255), nullable=False)
    recipient_email   = Column(String(255))
    subject           = Column(Text)
    received_datetime = Column(DateTime(timezone=True), nullable=False)
    status            = Column(String(30), default="RECEIVED", index=True)
    status_reason     = Column(Text)
    attachment_count  = Column(Integer, default=0)
    merged_pdf_path   = Column(Text)

    # AI analysis columns (§1.2.3)
    sentiment          = Column(String(20))
    sentiment_score    = Column(Numeric(5, 4))
    primary_emotion    = Column(String(50))
    email_category     = Column(String(50))
    sensitivity_level  = Column(String(20))    # public | internal | confidential | restricted
    contains_pii       = Column(Boolean, default=False)
    pii_types_json     = Column(JSON, default=list)
    ai_model_version   = Column(String(50))

    processed_at = Column(DateTime(timezone=True))
    is_archived  = Column(Boolean, default=False, index=True)
    archived_at  = Column(DateTime(timezone=True))
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    integration = relationship("EmailIntegration")
    events      = relationship("EmailBatchEvent", back_populates="batch", cascade="all, delete-orphan")
    attachments = relationship("EmailBatchAttachment", back_populates="batch", cascade="all, delete-orphan")
    callbacks   = relationship("EmailBatchCallback", back_populates="batch", cascade="all, delete-orphan")


class EmailBatchEvent(Base):
    """Audit-log sub-table — one row per validation/processing event (§3.3)."""
    __tablename__ = "email_batch_events"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    parent_batch_id  = Column(Integer, ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False)
    batch_no         = Column(String(60), index=True)
    event_type       = Column(String(40), nullable=False)
    related_filename = Column(String(255))
    reply_sent       = Column(Boolean, default=False)
    reply_message_id = Column(String(512))
    details          = Column(JSON, default=dict)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("EmailBatch", back_populates="events")


class EmailBatchAttachment(Base):
    """One row per attachment file in a batch (§3.4)."""
    __tablename__ = "email_batch_attachments"

    id                     = Column(Integer, primary_key=True, autoincrement=True)
    parent_batch_id        = Column(Integer, ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False)
    batch_no               = Column(String(60), index=True)
    batch_source_filename  = Column(String(255), nullable=False)
    doc_type               = Column(String(20))
    file_size_bytes        = Column(Integer)
    received_date          = Column(DateTime(timezone=True))
    is_encrypted           = Column(Boolean, default=False)
    converted_pdf_path     = Column(Text)
    status                 = Column(String(20), default="PENDING")
    # PENDING | CONVERTED | SKIPPED_ENCRYPTED | SKIPPED_INVALID_TYPE | FAILED | MERGED
    status_reason          = Column(Text)
    created_at             = Column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("EmailBatch", back_populates="attachments")


class EmailBatchCallback(Base):
    """Client webhook notification delivery log (§3.5)."""
    __tablename__ = "email_batch_callbacks"

    id                          = Column(Integer, primary_key=True, autoincrement=True)
    parent_batch_id             = Column(Integer, ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False)
    batch_no                    = Column(String(60), index=True)
    process_result_status_code  = Column(String(20))
    process_result_message      = Column(Text)
    payload_json                = Column(JSON, default=dict)
    webhook_url                 = Column(Text)
    http_status_code            = Column(Integer)
    attempt_no                  = Column(SmallInteger, default=1)
    delivered                   = Column(Boolean, default=False)
    error_detail                = Column(Text)
    created_at                  = Column(DateTime(timezone=True), server_default=func.now())

    batch = relationship("EmailBatch", back_populates="callbacks")


class BatchSequence(Base):
    """Concurrency-safe per-prefix/day sequence counter for batch numbering (open question §11.3 — resolved as DB row lock)."""
    __tablename__ = "batch_sequences"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    sequence_key  = Column(String(80), unique=True, nullable=False, index=True)  # e.g. "CLM-PROD-20260905"
    last_value    = Column(Integer, nullable=False, default=0)
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EmailTemplate(Base):
    """Branded/localized auto-reply templates (open question #1 — resolved as a dedicated table).

    `integration_id=NULL` rows are global defaults used when no integration-specific
    override exists for the given (template_key, locale) pair.
    """
    __tablename__ = "email_templates"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    integration_id   = Column(Integer, ForeignKey("email_integrations.id", ondelete="CASCADE"), nullable=True, index=True)
    template_key      = Column(String(60), nullable=False, index=True)
    # domain_rejected | no_attachment | invalid_file_type | encrypted_file | success | failure
    locale            = Column(String(10), default="en")
    subject_template  = Column(Text, nullable=False)
    html_body_template = Column(Text, nullable=False)
    signature_html    = Column(Text)
    logo_url          = Column(Text)
    is_active         = Column(Boolean, default=True)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    integration = relationship("EmailIntegration")


class EmailTemplateVersion(Base):
    """Immutable snapshot of an integration template before each update."""
    __tablename__ = "email_template_versions"

    id                 = Column(Integer, primary_key=True, autoincrement=True)
    template_id        = Column(Integer, ForeignKey("email_templates.id", ondelete="CASCADE"), nullable=False, index=True)
    template_key       = Column(String(60), nullable=False)
    subject_template   = Column(Text, nullable=False)
    html_body_template = Column(Text, nullable=False)
    signature_html     = Column(Text)
    logo_url           = Column(Text)
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
