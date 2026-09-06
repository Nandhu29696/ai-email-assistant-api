"""Add email templates, retention & archival columns (open questions #1, #5, #8)

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade():
    # ── Retention (open question #5) ──
    op.add_column("email_integrations", sa.Column("retention_days", sa.Integer, server_default="90"))

    # ── Archival tracking on email_batches ──
    op.add_column("email_batches", sa.Column("is_archived", sa.Boolean, server_default=sa.false()))
    op.add_column("email_batches", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.create_index("ix_email_batches_is_archived", "email_batches", ["is_archived"])

    # ── email_templates (open question #1) ──
    op.create_table(
        "email_templates",
        sa.Column("id",                  sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("integration_id",      sa.Integer, sa.ForeignKey("email_integrations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("template_key",        sa.String(60), nullable=False),
        sa.Column("locale",              sa.String(10), server_default="en"),
        sa.Column("subject_template",    sa.Text, nullable=False),
        sa.Column("html_body_template",  sa.Text, nullable=False),
        sa.Column("is_active",           sa.Boolean, server_default=sa.true()),
        sa.Column("created_at",          sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",          sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_email_templates_integration_id", "email_templates", ["integration_id"])
    op.create_index("ix_email_templates_key", "email_templates", ["template_key"])


def downgrade():
    op.drop_table("email_templates")
    op.drop_column("email_batches", "archived_at")
    op.drop_column("email_batches", "is_archived")
    op.drop_column("email_integrations", "retention_days")
