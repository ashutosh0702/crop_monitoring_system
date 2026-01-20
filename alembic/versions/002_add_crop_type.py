"""Add crop_type and planting_date to farms table.

Revision ID: 002_add_crop_type
Revises: 001_initial_schema
Create Date: 2024-01-20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_add_crop_type'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add crop_type column
    op.add_column('farms', sa.Column('crop_type', sa.String(50), nullable=True))
    
    # Add planting_date column
    op.add_column('farms', sa.Column('planting_date', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove columns
    op.drop_column('farms', 'planting_date')
    op.drop_column('farms', 'crop_type')
