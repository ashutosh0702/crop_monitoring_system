"""Add last_analyzed_date to farms table for forward fill tracking.

Revision ID: 004_add_last_analyzed_date
Revises: 003_add_crop_index_stacks
Create Date: 2026-03-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '004_add_last_analyzed_date'
down_revision = '003_add_crop_index_stacks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add last_analyzed_date column to track forward fill schedule
    op.add_column('farms', sa.Column('last_analyzed_date', sa.DateTime(), nullable=True))
    # Add index for efficient scheduling queries
    op.create_index('ix_farms_last_analyzed_date', 'farms', ['last_analyzed_date'])


def downgrade() -> None:
    # Remove index and column
    op.drop_index('ix_farms_last_analyzed_date', table_name='farms')
    op.drop_column('farms', 'last_analyzed_date')
