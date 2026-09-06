"""Add auth, tracking, and logging tables

Revision ID: c1d2e3f4a5b6
Revises: a0d796215fb0
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'a0d796215fb0'
branch_labels = None
depends_on = None


def upgrade():
    # ── user_sessions ──────────────────────────────────────────
    op.create_table(
        "user_sessions",
        sa.Column("id",            sa.Integer,       primary_key=True, autoincrement=True),
        sa.Column("user_id",       sa.Integer,       sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_token", sa.String(512),   unique=True, nullable=False),
        sa.Column("ip_address",    sa.String(45)),
        sa.Column("user_agent",    sa.String(512)),
        sa.Column("is_active",     sa.Boolean,       default=True),
        sa.Column("expires_at",    sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at",  sa.DateTime(timezone=True)),
        sa.Column("revoked_at",    sa.DateTime(timezone=True)),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_sessions_user_id",       "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_refresh_token", "user_sessions", ["refresh_token"])

    # ── audit_logs ─────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id",            sa.Integer,    primary_key=True, autoincrement=True),
        sa.Column("user_id",       sa.Integer,    sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action",        sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50)),
        sa.Column("resource_id",   sa.Integer),
        sa.Column("ip_address",    sa.String(45)),
        sa.Column("user_agent",    sa.String(512)),
        sa.Column("status",        sa.String(20),  default="success"),
        sa.Column("details",       sa.JSON),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_user_id",    "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_action",     "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # ── api_request_logs ───────────────────────────────────────
    op.create_table(
        "api_request_logs",
        sa.Column("id",               sa.Integer,  primary_key=True, autoincrement=True),
        sa.Column("user_id",          sa.Integer,  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("method",           sa.String(10)),
        sa.Column("path",             sa.String(512)),
        sa.Column("query_params",     sa.Text),
        sa.Column("status_code",      sa.Integer),
        sa.Column("response_time_ms", sa.Integer),
        sa.Column("ip_address",       sa.String(45)),
        sa.Column("user_agent",       sa.String(512)),
        sa.Column("error_detail",     sa.Text),
        sa.Column("created_at",       sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_request_logs_user_id",    "api_request_logs", ["user_id"])
    op.create_index("ix_api_request_logs_path",       "api_request_logs", ["path"])
    op.create_index("ix_api_request_logs_status_code","api_request_logs", ["status_code"])
    op.create_index("ix_api_request_logs_created_at", "api_request_logs", ["created_at"])

    # ── email_response_tracker ─────────────────────────────────
    op.create_table(
        "email_response_tracker",
        sa.Column("id",                     sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email_id",               sa.Integer, sa.ForeignKey("emails.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reply_id",               sa.Integer, sa.ForeignKey("email_replies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("responded_by_user_id",   sa.Integer),
        sa.Column("status",                 sa.String(20), default="pending"),
        sa.Column("first_response_minutes", sa.Integer),
        sa.Column("escalated_to",           sa.String(100)),
        sa.Column("sla_breach",             sa.Boolean, default=False),
        sa.Column("notes",                  sa.Text),
        sa.Column("created_at",             sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",             sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_email_response_tracker_email_id", "email_response_tracker", ["email_id"], unique=True)
    op.create_index("ix_email_response_tracker_status",   "email_response_tracker", ["status"])

    # ── Alter users: add new columns ───────────────────────────
    op.add_column("users", sa.Column("last_login_at",      sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("failed_login_count", sa.Integer, server_default="0"))
    op.add_column("users", sa.Column("locked_until",       sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_table("email_response_tracker")
    op.drop_table("api_request_logs")
    op.drop_table("audit_logs")
    op.drop_table("user_sessions")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "last_login_at")
