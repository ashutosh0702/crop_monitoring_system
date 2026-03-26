"""
SQLAlchemy models with GeoAlchemy2 for PostGIS support.
These models replace the JSON-based storage with proper database schema.
"""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Column, String, Float, Boolean, DateTime, ForeignKey, Text, JSON, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship, declarative_base
from geoalchemy2 import Geometry

from src.core.utils import file_to_data_url

Base = declarative_base()


class User(Base):
    """User model for authentication."""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone_number = Column(String(15), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
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
    
    # Crop information
    crop_type = Column(String(50), nullable=True)  # e.g., "wheat", "rice", "cotton"
    planting_date = Column(DateTime, nullable=True)  # When the crop was planted
    
    # PostGIS geometry column - stores GeoJSON as native geometry
    boundary = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    
    area_acres = Column(Float, nullable=True)
    last_analyzed_date = Column(DateTime, nullable=True, index=True)  # Track for forward fill efficiency
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    
    # Relationships
    owner = relationship("User", back_populates="farms")
    analyses = relationship("NDVIAnalysis", back_populates="farm", cascade="all, delete-orphan", order_by="desc(NDVIAnalysis.created_at)")
    index_stacks = relationship(
        "CropIndexStack",
        back_populates="farm",
        cascade="all, delete-orphan",
        order_by="desc(CropIndexStack.scene_date)",
    )
    
    # Note: Spatial index on 'boundary' is auto-created by GeoAlchemy2
    
    @property
    def latest_analysis(self) -> Optional["NDVIAnalysis"]:
        """Get the most recent analysis for this farm."""
        return self.analyses[0] if self.analyses else None
    
    def __repr__(self):
        return f"<Farm(id={self.id}, name={self.name}, crop={self.crop_type})>"


class NDVIAnalysis(Base):
    """NDVI Analysis results with file URLs and statistics."""
    __tablename__ = "ndvi_analyses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    farm_id = Column(UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False, index=True)
    
    # File URLs - local path or S3 URL
    tiff_url = Column(Text, nullable=False)
    png_url = Column(Text, nullable=True, default="placeholder")  # Colorized NDVI preview
    
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
    
    created_at = Column(DateTime, default=func.now())
    
    # Relationships
    farm = relationship("Farm", back_populates="analyses")
    
    def __repr__(self):
        return f"<NDVIAnalysis(id={self.id}, mean_ndvi={self.mean_ndvi}, status={self.status})>"
    
    def to_dict(self, include_payload: bool = True, bbox: Optional[list] = None) -> dict:
        """Convert to dictionary for API responses."""
        res = {
            "id": str(self.id),
            "tiff_url": self.tiff_url,
            "png_url": self.png_url,
            "bbox": bbox,
            "stats": {
                "mean_ndvi": round(self.mean_ndvi, 3) if self.mean_ndvi is not None else None,
                "min_ndvi": round(self.min_ndvi, 3) if self.min_ndvi is not None else None,
                "max_ndvi": round(self.max_ndvi, 3) if self.max_ndvi is not None else None,
                "std_ndvi": round(self.std_ndvi, 3) if self.std_ndvi is not None else None,
                "status": self.status,
                "timestamp": self.created_at.isoformat() if self.created_at else None,
            },
            "metadata": {
                "satellite_source": self.satellite_source,
                "scene_date": self.scene_date.isoformat() if self.scene_date else None,
                "cloud_cover": round(self.cloud_cover, 3) if self.cloud_cover is not None else None,
            },
        }
        if include_payload:
            res["png_data_url"] = file_to_data_url(self.png_url, "image/png")
        return res


class Alert(Base):
    """Alerts for NDVI threshold breaches and monitoring."""
    __tablename__ = "alerts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    farm_id = Column(UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False, index=True)
    
    alert_type = Column(String(50), nullable=False)  # NDVI_DROP, WEATHER_WARNING, etc.
    severity = Column(String(20), nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    message = Column(Text, nullable=False)
    
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    
    # Relationship
    farm = relationship("Farm")
    
    def __repr__(self):
        return f"<Alert(id={self.id}, type={self.alert_type}, severity={self.severity})>"


class CropIndexStack(Base):
    """Persisted multi-band vegetation index stack for a farm scene date."""

    __tablename__ = "crop_index_stacks"
    __table_args__ = (
        UniqueConstraint("farm_id", "scene_date", "satellite_source", name="uq_crop_index_stacks_farm_scene_source"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    farm_id = Column(UUID(as_uuid=True), ForeignKey("farms.id"), nullable=False, index=True)
    scene_date = Column(DateTime, nullable=False, index=True)

    stack_tiff_url = Column(Text, nullable=False)
    indices = Column(JSON, nullable=False)
    band_order = Column(JSON, nullable=False)

    satellite_source = Column(String(50), nullable=False, default="sentinel-2")
    cloud_cover = Column(Float, nullable=True)

    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    farm = relationship("Farm", back_populates="index_stacks")

    def __repr__(self):
        return f"<CropIndexStack(id={self.id}, farm_id={self.farm_id}, scene_date={self.scene_date})>"

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "farm_id": str(self.farm_id),
            "scene_date": self.scene_date.isoformat() if self.scene_date else None,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
            "indices": self.indices,
            "summary": self._build_summary(),
            "source": self.satellite_source,
            "stack_tiff_url": self.stack_tiff_url,
            "band_order": self.band_order,
            "cloud_cover": round(self.cloud_cover, 3) if self.cloud_cover is not None else None,
        }

    def _build_summary(self) -> dict:
        ndvi_mean = (self.indices.get("NDVI") or {}).get("mean")
        ndmi_mean = (self.indices.get("NDMI") or {}).get("mean")
        evi_mean = (self.indices.get("EVI") or {}).get("mean")

        recommendations = []
        if ndvi_mean is not None and ndvi_mean < 0.3:
            recommendations.append("Low vegetation detected - inspect crop vigor")
        elif ndvi_mean is not None and ndvi_mean > 0.6:
            recommendations.append("Dense healthy vegetation - maintain current practices")

        if ndmi_mean is not None and ndmi_mean < 0:
            recommendations.append("Moisture stress detected - irrigation recommended")
        elif ndmi_mean is not None and ndmi_mean > 0.2:
            recommendations.append("Good canopy moisture levels")

        return {
            "overall_health": "GOOD" if ndvi_mean is not None and ndmi_mean is not None and ndvi_mean > 0.4 and ndmi_mean > 0 else "MODERATE" if ndvi_mean is not None and ndvi_mean > 0.25 else "POOR",
            "moisture_status": "ADEQUATE" if ndmi_mean is not None and ndmi_mean > 0 else "STRESSED",
            "vegetation_density": "HIGH" if evi_mean is not None and evi_mean > 0.4 else "MODERATE" if evi_mean is not None and evi_mean > 0.2 else "LOW",
            "recommendations": recommendations,
        }


class STACSceneCache(Base):
    """Cached Sentinel-2 scene footprints and band URLs."""
    __tablename__ = "stac_scene_cache"
    
    id = Column(String(100), primary_key=True)  # Scene ID e.g., S2A_...
    geom = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    datetime = Column(DateTime, nullable=False, index=True)
    cloud_cover = Column(Float, nullable=False)
    assets = Column(JSON, nullable=False)  # URLs (red, nir, blue, etc.)
    created_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f"<STACSceneCache(id={self.id}, datetime={self.datetime})>"


class STACSearchRegion(Base):
    """Regions that have already been queried against Earth Search API."""
    __tablename__ = "stac_search_regions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    geom = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    max_cloud_cover = Column(Float, nullable=False)
    created_at = Column(DateTime, default=func.now())
    
    def __repr__(self):
        return f"<STACSearchRegion(start={self.start_date}, end={self.end_date})>"
