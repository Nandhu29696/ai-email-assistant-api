"""Add configurable success and failure document-intake auto-replies.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_integrations", sa.Column("success_auto_reply_enabled", sa.Boolean, server_default=sa.false()))
    op.add_column("email_integrations", sa.Column("failure_auto_reply_enabled", sa.Boolean, server_default=sa.false()))


def downgrade():
    op.drop_column("email_integrations", "failure_auto_reply_enabled")
    op.drop_column("email_integrations", "success_auto_reply_enabled")