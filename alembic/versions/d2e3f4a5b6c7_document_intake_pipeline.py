"""Add document intake batch processing pipeline tables

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    # ── Extend email_integrations with document-intake settings (§3.1) ──
    op.add_column("email_integrations", sa.Column("batch_prefix", sa.String(10)))
    op.add_column("email_integrations", sa.Column("mailbox_type", sa.String(10), server_default="PROD"))
    op.add_column("email_integrations", sa.Column("processing_mode", sa.String(20), server_default="conversation"))
    op.add_column("email_integrations", sa.Column("allowed_extensions", sa.String(100), server_default="pdf,doc,docx,tiff,tif"))
    op.add_column("email_integrations", sa.Column("max_file_size_mb", sa.Integer, server_default="25"))
    op.add_column("email_integrations", sa.Column("auto_reply_no_attachment", sa.Boolean, server_default=sa.true()))
    op.add_column("email_integrations", sa.Column("auto_reply_invalid_domain", sa.Boolean, server_default=sa.true()))
    op.add_column("email_integrations", sa.Column("success_folder_label", sa.String(100), server_default="Processed/Success"))
    op.add_column("email_integrations", sa.Column("failed_folder_label", sa.String(100), server_default="Processed/Failed"))
    op.add_column("email_integrations", sa.Column("storage_provider", sa.String(20), server_default="local"))
    op.add_column("email_integrations", sa.Column("callback_webhook_url", sa.Text))
    op.add_column("email_integrations", sa.Column("callback_auth_header", sa.Text))
    op.add_column("email_integrations", sa.Column("callback_enabled", sa.Boolean, server_default=sa.false()))

    # ── batch_sequences (concurrency-safe batch numbering, §11.3) ──
    op.create_table(
        "batch_sequences",
        sa.Column("id",           sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("sequence_key", sa.String(80), unique=True, nullable=False),
        sa.Column("last_value",   sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at",   sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_batch_sequences_key", "batch_sequences", ["sequence_key"])

    # ── email_batches (parent table, §3.2) ──
    op.create_table(
        "email_batches",
        sa.Column("id",                sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("batch_no",          sa.String(60), unique=True, nullable=False),
        sa.Column("message_id",        sa.String(512), unique=True, nullable=False),
        sa.Column("conversation_id",   sa.String(512)),
        sa.Column("integration_id",    sa.Integer, sa.ForeignKey("email_integrations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mailbox_type",      sa.String(10)),
        sa.Column("email_type",        sa.String(30), server_default="inbound_document"),
        sa.Column("sender_email",      sa.String(255), nullable=False),
        sa.Column("recipient_email",   sa.String(255)),
        sa.Column("subject",           sa.Text),
        sa.Column("received_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status",            sa.String(30), server_default="RECEIVED"),
        sa.Column("status_reason",     sa.Text),
        sa.Column("attachment_count",  sa.Integer, server_default="0"),
        sa.Column("merged_pdf_path",   sa.Text),
        sa.Column("sentiment",         sa.String(20)),
        sa.Column("sentiment_score",   sa.Numeric(5, 4)),
        sa.Column("primary_emotion",   sa.String(50)),
        sa.Column("email_category",    sa.String(50)),
        sa.Column("sensitivity_level", sa.String(20)),
        sa.Column("contains_pii",      sa.Boolean, server_default=sa.false()),
        sa.Column("pii_types_json",    sa.JSON),
        sa.Column("ai_model_version",  sa.String(50)),
        sa.Column("processed_at",      sa.DateTime(timezone=True)),
        sa.Column("created_at",        sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",        sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_email_batches_batch_no", "email_batches", ["batch_no"])
    op.create_index("ix_email_batches_message_id", "email_batches", ["message_id"])
    op.create_index("ix_email_batches_status", "email_batches", ["status"])
    op.create_index("ix_email_batches_received_datetime", "email_batches", ["received_datetime"])

    # ── email_batch_events (audit log sub-table, §3.3) ──
    op.create_table(
        "email_batch_events",
        sa.Column("id",               sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("parent_batch_id",  sa.Integer, sa.ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_no",         sa.String(60)),
        sa.Column("event_type",       sa.String(40), nullable=False),
        sa.Column("related_filename", sa.String(255)),
        sa.Column("reply_sent",       sa.Boolean, server_default=sa.false()),
        sa.Column("reply_message_id", sa.String(512)),
        sa.Column("details",          sa.JSON),
        sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_email_batch_events_batch_no", "email_batch_events", ["batch_no"])

    # ── email_batch_attachments (§3.4) ──
    op.create_table(
        "email_batch_attachments",
        sa.Column("id",                    sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("parent_batch_id",       sa.Integer, sa.ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_no",              sa.String(60)),
        sa.Column("batch_source_filename", sa.String(255), nullable=False),
        sa.Column("doc_type",              sa.String(20)),
        sa.Column("file_size_bytes",       sa.Integer),
        sa.Column("received_date",         sa.DateTime(timezone=True)),
        sa.Column("is_encrypted",          sa.Boolean, server_default=sa.false()),
        sa.Column("converted_pdf_path",    sa.Text),
        sa.Column("status",                sa.String(20), server_default="PENDING"),
        sa.Column("status_reason",         sa.Text),
        sa.Column("created_at",            sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_email_batch_attachments_batch_no", "email_batch_attachments", ["batch_no"])

    # ── email_batch_callbacks (client notification delivery log, §3.5) ──
    op.create_table(
        "email_batch_callbacks",
        sa.Column("id",                         sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("parent_batch_id",            sa.Integer, sa.ForeignKey("email_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_no",                   sa.String(60)),
        sa.Column("process_result_status_code", sa.String(20)),
        sa.Column("process_result_message",     sa.Text),
        sa.Column("payload_json",                sa.JSON),
        sa.Column("webhook_url",                sa.Text),
        sa.Column("http_status_code",           sa.Integer),
        sa.Column("attempt_no",                 sa.SmallInteger, server_default="1"),
        sa.Column("delivered",                  sa.Boolean, server_default=sa.false()),
        sa.Column("error_detail",               sa.Text),
        sa.Column("created_at",                 sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_email_batch_callbacks_batch_no", "email_batch_callbacks", ["batch_no"])


def downgrade():
    op.drop_table("email_batch_callbacks")
    op.drop_table("email_batch_attachments")
    op.drop_table("email_batch_events")
    op.drop_table("email_batches")
    op.drop_table("batch_sequences")

    for col in (
        "batch_prefix", "mailbox_type", "processing_mode", "allowed_extensions",
        "max_file_size_mb", "auto_reply_no_attachment", "auto_reply_invalid_domain",
        "success_folder_label", "failed_folder_label", "storage_provider",
        "callback_webhook_url", "callback_auth_header", "callback_enabled",
    ):
        op.drop_column("email_integrations", col)
