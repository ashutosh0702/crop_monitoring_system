"""Add crop_index_stacks table.

Revision ID: 003_add_crop_index_stacks
Revises: 002_add_crop_type
Create Date: 2026-03-25

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "003_add_crop_index_stacks"
down_revision: Union[str, None] = "002_add_crop_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crop_index_stacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("farm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_date", sa.DateTime(), nullable=False),
        sa.Column("stack_tiff_url", sa.Text(), nullable=False),
        sa.Column("indices", sa.JSON(), nullable=False),
        sa.Column("band_order", sa.JSON(), nullable=False),
        sa.Column("satellite_source", sa.String(length=50), nullable=False),
        sa.Column("cloud_cover", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["farm_id"], ["farms.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("farm_id", "scene_date", "satellite_source", name="uq_crop_index_stacks_farm_scene_source"),
    )
    op.create_index("ix_crop_index_stacks_farm_id", "crop_index_stacks", ["farm_id"])
    op.create_index("ix_crop_index_stacks_scene_date", "crop_index_stacks", ["scene_date"])


def downgrade() -> None:
    op.drop_index("ix_crop_index_stacks_scene_date", table_name="crop_index_stacks")
    op.drop_index("ix_crop_index_stacks_farm_id", table_name="crop_index_stacks")
    op.drop_table("crop_index_stacks")
