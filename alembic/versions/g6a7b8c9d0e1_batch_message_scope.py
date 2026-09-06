"""Add integration-scoped idempotency constraint for document batches."""
from alembic import op


revision = "g6a7b8c9d0e1"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_email_batches_integration_message",
        "email_batches",
        ["integration_id", "message_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_email_batches_integration_message",
        "email_batches",
        type_="unique",
    )