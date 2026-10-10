"""Per-mailbox pickup interval (seconds between checks for new email)."""
from alembic import op
import sqlalchemy as sa


revision = "o4c5d6e7f8a9"
down_revision = "n3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_integrations", sa.Column("fetch_interval_seconds", sa.Integer()))


def downgrade():
    op.drop_column("email_integrations", "fetch_interval_seconds")
