"""Enhancements: MFA, per-mailbox policies (domains, categories, SLA, signature,
IMAP credentials), Gmail history sync, per-user notifications, dead-letter jobs.
"""
from alembic import op
import sqlalchemy as sa


revision = "l1f2a3b4c5d6"
down_revision = "k0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade():
    # ── users: optional TOTP MFA ─────────────────────────────
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("mfa_secret", sa.Text()))              # encrypted
    op.add_column("users", sa.Column("mfa_recovery_codes", sa.JSON()))      # SHA-256 hashes
    op.add_column("users", sa.Column("mfa_last_used_step", sa.BigInteger()))

    # ── email_integrations: per-mailbox policy + provider state ──
    for column in (
        sa.Column("allowed_sender_domains", sa.Text()),
        sa.Column("auto_reply_allowed_categories", sa.String(200)),
        sa.Column("auto_reply_denied_categories", sa.String(200)),
        sa.Column("sla_thresholds", sa.JSON()),
        sa.Column("reply_signature_html", sa.Text()),
        sa.Column("gmail_history_id", sa.String(40)),
        sa.Column("gmail_watch_expires_at", sa.DateTime(timezone=True)),
        sa.Column("imap_host", sa.String(255)),
        sa.Column("imap_port", sa.Integer()),
        sa.Column("imap_username", sa.String(255)),
        sa.Column("imap_password", sa.Text()),                               # encrypted
        sa.Column("smtp_host", sa.String(255)),
        sa.Column("smtp_port", sa.Integer()),
        sa.Column("smtp_username", sa.String(255)),
        sa.Column("smtp_password", sa.Text()),                               # encrypted
    ):
        op.add_column("email_integrations", column)

    # ── emails: provider id for threaded replies, sender authentication ──
    op.add_column("emails", sa.Column("provider_message_id", sa.String(255)))
    op.add_column("emails", sa.Column("sender_auth_failed", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.add_column("email_replies", sa.Column("review_reason", sa.Text()))

    # ── per-user notifications ───────────────────────────────
    op.add_column("notifications", sa.Column("user_id", sa.Integer()))
    op.create_foreign_key("fk_notifications_user_id", "notifications", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_table(
        "notification_reads",
        sa.Column("notification_id", sa.Integer(), sa.ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # Backfill owners for existing notifications so clients keep seeing them.
    op.execute(sa.text(
        "UPDATE notifications SET user_id = ("
        " SELECT email_integrations.owner_user_id FROM emails"
        " JOIN email_integrations ON emails.integration_id = email_integrations.id"
        " WHERE emails.id = notifications.email_id)"
        " WHERE user_id IS NULL AND email_id IS NOT NULL"
    ))

    # ── dead-letter queue for background jobs ────────────────
    op.create_table(
        "failed_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_name", sa.String(100), nullable=False, index=True),
        sa.Column("args_json", sa.JSON()),
        sa.Column("job_key", sa.String(255)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="failed", index=True),  # failed | retried | discarded
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("failed_jobs")
    op.drop_table("notification_reads")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_constraint("fk_notifications_user_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "user_id")
    op.drop_column("email_replies", "review_reason")
    op.drop_column("emails", "sender_auth_failed")
    op.drop_column("emails", "provider_message_id")
    for name in (
        "smtp_password", "smtp_username", "smtp_port", "smtp_host",
        "imap_password", "imap_username", "imap_port", "imap_host",
        "gmail_watch_expires_at", "gmail_history_id", "reply_signature_html", "sla_thresholds",
        "auto_reply_denied_categories", "auto_reply_allowed_categories", "allowed_sender_domains",
    ):
        op.drop_column("email_integrations", name)
    for name in ("mfa_last_used_step", "mfa_recovery_codes", "mfa_secret", "mfa_enabled"):
        op.drop_column("users", name)
