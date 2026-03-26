"""Add business_id column to background_jobs.

Allows querying active jobs by business_id for job-type-agnostic
blocking in frontends (e.g. MrCall Dashboard blocks chat when any
job is running for a business).

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-13
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("background_jobs", sa.Column("business_id", sa.Text(), nullable=True))
    op.create_index("ix_background_jobs_business_id", "background_jobs", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_background_jobs_business_id", table_name="background_jobs")
    op.drop_column("background_jobs", "business_id")
