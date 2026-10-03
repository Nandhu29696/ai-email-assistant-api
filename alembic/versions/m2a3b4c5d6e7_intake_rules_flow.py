"""Intake rules flow: email content/PDF and rule outcome per email; mailbox start time.

Tables of the retired conversation features are kept (not dropped) so their data
is preserved; see FUTURE_ENHANCEMENTS.md.
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "m2a3b4c5d6e7"
down_revision = "l1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("email_integrations", sa.Column("process_since", sa.DateTime(timezone=True)))
    # Existing mailboxes start from now: their old backlog must not be auto-replied.
    op.execute(
        sa.text("UPDATE email_integrations SET process_since = :now WHERE process_since IS NULL")
        .bindparams(now=datetime.now(timezone.utc).replace(tzinfo=None))
    )

    op.add_column("email_batches", sa.Column("sender_name", sa.String(255)))
    op.add_column("email_batches", sa.Column("body_text", sa.Text()))
    op.add_column("email_batches", sa.Column("outcome", sa.String(40)))
    op.add_column("email_batches", sa.Column("email_pdf_path", sa.Text()))
    op.create_index("ix_email_batches_outcome", "email_batches", ["outcome"])


def downgrade():
    op.drop_index("ix_email_batches_outcome", table_name="email_batches")
    for column in ("email_pdf_path", "outcome", "body_text", "sender_name"):
        op.drop_column("email_batches", column)
    op.drop_column("email_integrations", "process_since")
