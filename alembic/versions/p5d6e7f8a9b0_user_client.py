"""Third role level: a "user" belongs to a client account (users.client_id)."""
from alembic import op
import sqlalchemy as sa


revision = "p5d6e7f8a9b0"
down_revision = "o4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("client_id", sa.Integer()))
    op.create_index("ix_users_client_id", "users", ["client_id"])
    op.create_foreign_key("fk_users_client_id", "users", "users", ["client_id"], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("fk_users_client_id", "users", type_="foreignkey")
    op.drop_index("ix_users_client_id", table_name="users")
    op.drop_column("users", "client_id")
