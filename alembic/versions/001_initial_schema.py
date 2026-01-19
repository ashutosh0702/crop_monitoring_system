"""Initial schema with PostGIS

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-01-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable PostGIS extension
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('phone_number', sa.String(length=15), nullable=False),
        sa.Column('full_name', sa.String(length=100), nullable=False),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_phone_number', 'users', ['phone_number'], unique=True)
    
    # Create farms table with PostGIS geometry
    op.create_table(
        'farms',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('boundary', geoalchemy2.Geometry(geometry_type='POLYGON', srid=4326), nullable=False),
        sa.Column('area_acres', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_farms_owner_id', 'farms', ['owner_id'])
    op.create_index('idx_farms_boundary', 'farms', ['boundary'], postgresql_using='gist')
    
    # Create ndvi_analyses table
    op.create_table(
        'ndvi_analyses',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('farm_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tiff_url', sa.Text(), nullable=False),
        sa.Column('png_url', sa.Text(), nullable=True, default='placeholder'),
        sa.Column('mean_ndvi', sa.Float(), nullable=False),
        sa.Column('min_ndvi', sa.Float(), nullable=True),
        sa.Column('max_ndvi', sa.Float(), nullable=True),
        sa.Column('std_ndvi', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('satellite_source', sa.String(length=50), nullable=True, default='mock'),
        sa.Column('scene_date', sa.DateTime(), nullable=True),
        sa.Column('cloud_cover', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ndvi_analyses_farm_id', 'ndvi_analyses', ['farm_id'])
    
    # Create alerts table
    op.create_table(
        'alerts',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('farm_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('alert_type', sa.String(length=50), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=True, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_alerts_farm_id', 'alerts', ['farm_id'])


def downgrade() -> None:
    op.drop_table('alerts')
    op.drop_table('ndvi_analyses')
    op.drop_table('farms')
    op.drop_table('users')
    op.execute('DROP EXTENSION IF EXISTS postgis')
