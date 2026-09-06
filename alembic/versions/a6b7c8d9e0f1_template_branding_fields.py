"""Add logo and signature fields to email templates.

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_templates", sa.Column("signature_html", sa.Text))
    op.add_column("email_templates", sa.Column("logo_url", sa.Text))


def downgrade():
    op.drop_column("email_templates", "logo_url")
    op.drop_column("email_templates", "signature_html")