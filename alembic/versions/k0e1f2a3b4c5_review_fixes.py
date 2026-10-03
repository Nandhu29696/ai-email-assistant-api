"""Review fixes: per-mailbox message uniqueness, auto-reply toggle, Outlook
subscription tracking, reply review flag.

Existing refresh tokens were stored in plaintext; they are now stored as
SHA-256 hashes, so active sessions are revoked and users sign in again.
"""
from alembic import op
import sqlalchemy as sa


revision = "k0e1f2a3b4c5"
down_revision = "j9d0e1f2a3b4"
branch_labels = None
depends_on = None


def _drop_single_column_unique(table: str, column: str) -> None:
    """Drop the unnamed UNIQUE(column) created by the initial schema.

    PostgreSQL names it ``<table>_<column>_key``; MySQL names the backing index
    after the column. Look it up instead of guessing.
    """
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_unique_constraints(table):
        if constraint.get("column_names") == [column] and constraint.get("name"):
            op.drop_constraint(constraint["name"], table, type_="unique")
            return
    for index in inspector.get_indexes(table):
        if index.get("unique") and index.get("column_names") == [column]:
            op.drop_index(index["name"], table_name=table)
            return


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not any(fk.get("referred_table") == "emails" for fk in inspector.get_foreign_keys("notifications")):
        # Fresh databases built from a00000000000 lack this FK; older ones already have it.
        op.create_foreign_key(
            "fk_notifications_email_id", "notifications", "emails", ["email_id"], ["id"], ondelete="CASCADE",
        )

    # g6a7b8c9d0e1 added UNIQUE(integration_id, message_id) for batches but left
    # the global UNIQUE(message_id), so one email sent to two intake mailboxes failed.
    _drop_single_column_unique("email_batches", "message_id")
    if not any(ix.get("column_names") == ["message_id"] for ix in inspector.get_indexes("email_batches")):
        op.create_index("ix_email_batches_message_id", "email_batches", ["message_id"])

    _drop_single_column_unique("emails", "message_id")
    op.create_index("ix_emails_message_id", "emails", ["message_id"])
    op.create_unique_constraint(
        "uq_emails_integration_message", "emails", ["integration_id", "message_id"],
    )

    op.add_column(
        "email_integrations",
        sa.Column("auto_reply_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("email_integrations", sa.Column("outlook_subscription_id", sa.String(255)))
    op.add_column(
        "email_integrations",
        sa.Column("outlook_subscription_expires_at", sa.DateTime(timezone=True)),
    )

    op.add_column(
        "email_replies",
        sa.Column("requires_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # "employee" was never a valid role for the API; treat those users as clients.
    op.execute(sa.text("UPDATE users SET role = 'client' WHERE role = 'employee'"))

    # Refresh tokens are now stored hashed; plaintext rows can never match again.
    op.execute(
        sa.text(
            "UPDATE user_sessions SET is_active = :inactive, revoked_at = CURRENT_TIMESTAMP "
            "WHERE is_active = :active"
        ).bindparams(inactive=False, active=True)
    )


def downgrade():
    op.drop_column("email_replies", "requires_review")
    op.drop_column("email_integrations", "outlook_subscription_expires_at")
    op.drop_column("email_integrations", "outlook_subscription_id")
    op.drop_column("email_integrations", "auto_reply_enabled")
    op.drop_constraint("uq_emails_integration_message", "emails", type_="unique")
    op.drop_index("ix_emails_message_id", table_name="emails")
    op.create_unique_constraint("emails_message_id_key", "emails", ["message_id"])
    # The global UNIQUE(email_batches.message_id) is intentionally not restored.
    inspector = sa.inspect(op.get_bind())
    if any(fk.get("name") == "fk_notifications_email_id" for fk in inspector.get_foreign_keys("notifications")):
        op.drop_constraint("fk_notifications_email_id", "notifications", type_="foreignkey")
