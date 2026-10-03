"""Priority and AI summary per email.

Retention columns (email_integrations.retention_days, email_batches.is_archived /
archived_at) already exist from e3f4a5b6c7d8 and are mapped again by the models.
"""
from alembic import op
import sqlalchemy as sa


revision = "n3b4c5d6e7f8"
down_revision = "m2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_batches", sa.Column("priority", sa.String(20)))
    op.add_column("email_batches", sa.Column("ai_summary", sa.Text()))
    op.create_index("ix_email_batches_priority", "email_batches", ["priority"])


def downgrade():
    op.drop_index("ix_email_batches_priority", table_name="email_batches")
    op.drop_column("email_batches", "ai_summary")
    op.drop_column("email_batches", "priority")
