"""stac_cache

Revision ID: 9ce433a36f3b
Revises: 004_add_last_analyzed_date
Create Date: 2026-03-26 11:45:05.660800+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9ce433a36f3b'
down_revision: Union[str, None] = '004_add_last_analyzed_date'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create stac_scene_cache
    op.create_table('stac_scene_cache',
        sa.Column('id', sa.String(length=100), nullable=False),
        sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POLYGON', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
        sa.Column('datetime', sa.DateTime(), nullable=False),
        sa.Column('cloud_cover', sa.Float(), nullable=False),
        sa.Column('assets', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # Index 'idx_stac_scene_cache_geom' is created automatically by GeoAlchemy2 CREATE TABLE
    op.create_index(op.f('ix_stac_scene_cache_datetime'), 'stac_scene_cache', ['datetime'], unique=False)

    # 2. Create stac_search_regions
    op.create_table('stac_search_regions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POLYGON', srid=4326, dimension=2, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
        sa.Column('start_date', sa.DateTime(), nullable=False),
        sa.Column('end_date', sa.DateTime(), nullable=False),
        sa.Column('max_cloud_cover', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    # Index 'idx_stac_search_regions_geom' is created automatically by GeoAlchemy2 CREATE TABLE


def downgrade() -> None:
    op.drop_table('stac_search_regions')
    op.drop_table('stac_scene_cache')
