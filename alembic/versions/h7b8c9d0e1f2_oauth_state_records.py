"""Add one-time OAuth state records."""
from alembic import op
import sqlalchemy as sa


revision = "h7b8c9d0e1f2"
down_revision = "g6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_oauth_states_state_hash", "oauth_states", ["state_hash"])
    op.create_index("ix_oauth_states_user_id", "oauth_states", ["user_id"])
    op.create_index("ix_oauth_states_expires_at", "oauth_states", ["expires_at"])


def downgrade():
    op.drop_table("oauth_states")