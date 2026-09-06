"""Add client role ownership to integrations

Revision ID: e4f5a6b7c8d9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-05
"""
from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE users SET role = 'client' WHERE role = 'employee'")
    op.add_column(
        "email_integrations",
        sa.Column("owner_user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_email_integrations_owner_user_id", "email_integrations", ["owner_user_id"])


def downgrade():
    op.drop_index("ix_email_integrations_owner_user_id", table_name="email_integrations")
    op.drop_column("email_integrations", "owner_user_id")
