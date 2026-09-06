"""Add template version history and integration health metadata.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_integrations", sa.Column("last_sync_at", sa.DateTime(timezone=True)))
    op.add_column("email_integrations", sa.Column("last_email_processed_at", sa.DateTime(timezone=True)))
    op.add_column("email_integrations", sa.Column("health_status", sa.String(20), server_default="unknown"))
    op.add_column("email_integrations", sa.Column("health_message", sa.Text))
    op.create_table(
        "email_template_versions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("template_id", sa.Integer, sa.ForeignKey("email_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_key", sa.String(60), nullable=False),
        sa.Column("subject_template", sa.Text, nullable=False),
        sa.Column("html_body_template", sa.Text, nullable=False),
        sa.Column("signature_html", sa.Text),
        sa.Column("logo_url", sa.Text),
        sa.Column("created_by_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_email_template_versions_template_id", "email_template_versions", ["template_id"])


def downgrade():
    op.drop_table("email_template_versions")
    op.drop_column("email_integrations", "health_message")
    op.drop_column("email_integrations", "health_status")
    op.drop_column("email_integrations", "last_email_processed_at")
    op.drop_column("email_integrations", "last_sync_at")