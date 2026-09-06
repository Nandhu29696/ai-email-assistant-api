"""Add per-mailbox conversational analysis setting."""
from alembic import op
import sqlalchemy as sa


revision = "j9d0e1f2a3b4"
down_revision = "i8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "email_integrations",
        sa.Column(
            "conversation_analysis_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade():
    op.drop_column("email_integrations", "conversation_analysis_enabled")