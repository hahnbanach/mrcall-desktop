"""Add error_logs table for API error tracking.

Logs transient errors (Anthropic 529, etc.) with business context,
Haiku-generated user messages, and request IDs for debugging.

Revision ID: 0003
Revises: 0001
Create Date: 2026-03-27
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "error_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Text(), nullable=False, index=True),
        sa.Column("business_id", sa.Text(), index=True),
        sa.Column("session_id", sa.Text(), index=True),
        sa.Column("error_type", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Integer()),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("user_message", sa.Text()),
        sa.Column("request_id", sa.Text()),
        sa.Column("context", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("error_logs")
