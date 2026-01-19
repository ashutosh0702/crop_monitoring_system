"""
SQLAlchemy models with GeoAlchemy2 for PostGIS support.
These models replace the JSON-based storage with proper database schema.
"""

from datetime import datetime
from typing import Optional, List
import uuid

from sqlalchemy import (
    Column, String, Float, Boolean, DateTime, ForeignKey, Text, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base
from geoalchemy2 import Geometry

Base = declarative_base()


class User(Base):
    """User model for authentication."""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number = Column(String(15), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    farms = relationship("Farm", back_populates="owner", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(id={self.id}, phone={self.phone_number})>"


class Farm(Base):
    """Farm/Field model with PostGIS geometry for boundaries."""
    __tablename__ = "farms"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    
    # PostGIS geometry column - stores GeoJSON as native geometry
    boundary = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    
    area_acres = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    owner = relationship("User", back_populates="farms")
    analyses = relationship("NDVIAnalysis", back_populates="farm", cascade="all, delete-orphan", order_by="desc(NDVIAnalysis.created_at)")
    
    # Note: Spatial index on 'boundary' is auto-created by GeoAlchemy2
    
    @property
    def latest_analysis(self) -> Optional["NDVIAnalysis"]:
        """Get the most recent analysis for this farm."""
        return self.analyses[0] if self.analyses else None
    
    def __repr__(self):
        return f"<Farm(id={self.id}, name={self.name})>"


class NDVIAnalysis(Base):
    """NDVI Analysis results with file URLs and statistics."""
    __tablename__ = "ndvi_analyses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    farm_id = Column(UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False, index=True)
    
    # File URLs - local path or S3 URL
    tiff_url = Column(Text, nullable=False)
    png_url = Column(Text, nullable=True, default="placeholder")  # False color composite
    
    # NDVI Statistics
    mean_ndvi = Column(Float, nullable=False)
    min_ndvi = Column(Float, nullable=True)
    max_ndvi = Column(Float, nullable=True)
    std_ndvi = Column(Float, nullable=True)
    
    # Classification
    status = Column(String(20), nullable=False)  # HEALTHY, MODERATE, CRITICAL, DATA_MISSING
    
    # Metadata
    satellite_source = Column(String(50), nullable=True, default="mock")  # mock, sentinel-2, etc.
    scene_date = Column(DateTime, nullable=True)  # Date of satellite imagery
    cloud_cover = Column(Float, nullable=True)  # Percentage cloud cover
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    farm = relationship("Farm", back_populates="analyses")
    
    def __repr__(self):
        return f"<NDVIAnalysis(id={self.id}, mean_ndvi={self.mean_ndvi}, status={self.status})>"
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "tiff_url": self.tiff_url,
            "png_url": self.png_url,
            "stats": {
                "mean_ndvi": round(self.mean_ndvi, 3) if self.mean_ndvi else None,
                "min_ndvi": round(self.min_ndvi, 3) if self.min_ndvi else None,
                "max_ndvi": round(self.max_ndvi, 3) if self.max_ndvi else None,
                "status": self.status,
                "timestamp": self.created_at.isoformat() if self.created_at else None,
            },
            "satellite_source": self.satellite_source,
            "scene_date": self.scene_date.isoformat() if self.scene_date else None,
        }


class Alert(Base):
    """Alerts for NDVI threshold breaches and monitoring."""
    __tablename__ = "alerts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    farm_id = Column(UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False, index=True)
    
    alert_type = Column(String(50), nullable=False)  # NDVI_DROP, WEATHER_WARNING, etc.
    severity = Column(String(20), nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    message = Column(Text, nullable=False)
    
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship
    farm = relationship("Farm")
    
    def __repr__(self):
        return f"<Alert(id={self.id}, type={self.alert_type}, severity={self.severity})>"
