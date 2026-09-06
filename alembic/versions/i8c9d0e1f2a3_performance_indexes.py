"""Add indexes for common email and notification queries."""
from alembic import op


revision = "i8c9d0e1f2a3"
down_revision = "h7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_emails_integration_received_at",
        "emails",
        ["integration_id", "received_at"],
    )
    op.create_index("ix_emails_received_at", "emails", ["received_at"])
    op.create_index("ix_emails_thread_id", "emails", ["thread_id"])
    op.create_index("ix_emails_is_read", "emails", ["is_read"])
    op.create_index(
        "ix_notifications_created_read",
        "notifications",
        ["created_at", "is_read"],
    )


def downgrade():
    op.drop_index("ix_notifications_created_read", table_name="notifications")
    op.drop_index("ix_emails_is_read", table_name="emails")
    op.drop_index("ix_emails_thread_id", table_name="emails")
    op.drop_index("ix_emails_received_at", table_name="emails")
    op.drop_index("ix_emails_integration_received_at", table_name="emails")