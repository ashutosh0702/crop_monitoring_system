from pydantic import BaseModel, Field, field_validator
from typing import List, Literal, Optional
from datetime import datetime
from enum import Enum


# --- Crop Type Enum ---

class CropType(str, Enum):
    """Common crop types for agricultural monitoring."""
    WHEAT = "wheat"
    RICE = "rice"
    COTTON = "cotton"
    CORN = "corn"
    SOYBEAN = "soybean"
    SUGARCANE = "sugarcane"
    VEGETABLES = "vegetables"
    FRUITS = "fruits"
    PULSES = "pulses"
    OILSEEDS = "oilseeds"
    OTHER = "other"


# --- 1. GeoJSON Sub-Models ---

class GeoJSONPolygon(BaseModel):
    """
    Standard GeoJSON Polygon structure.
    Example:
    {
        "type": "Polygon",
        "coordinates": [
            [[77.1, 28.5], [77.2, 28.5], [77.2, 28.6], [77.1, 28.6], [77.1, 28.5]]
        ]
    }
    """
    type: Literal["Polygon"] = "Polygon"
    coordinates: List[List[List[float]]]

    @field_validator("coordinates")
    @classmethod
    def validate_polygon_closure(cls, v):
        if not v:
            raise ValueError("Polygon must have at least one linear ring (boundary).")
        
        outer_ring = v[0]
        if len(outer_ring) < 4:
            raise ValueError("A Polygon LinearRing must have at least 4 points.")
        
        if outer_ring[0] != outer_ring[-1]:
            raise ValueError("The first and last coordinates must be the same to close the polygon.")
        
        return v


# --- 2. API Models ---

class FieldCreate(BaseModel):
    """Request model to create a new field with crop information."""
    name: str = Field(..., example="North River Field")
    boundary: GeoJSONPolygon
    crop_type: Optional[CropType] = Field(None, example="wheat", description="Type of crop planted")
    planting_date: Optional[datetime] = Field(None, example="2024-06-15T00:00:00", description="Date when crop was planted")


class FieldUpdate(BaseModel):
    """Request model to update field information."""
    name: Optional[str] = None
    crop_type: Optional[CropType] = None
    planting_date: Optional[datetime] = None


class NDVIStats(BaseModel):
    """NDVI statistical results."""
    mean_ndvi: float
    min_ndvi: Optional[float] = None
    max_ndvi: Optional[float] = None
    std_ndvi: Optional[float] = None
    status: str  # HEALTHY, MODERATE, CRITICAL, DATA_MISSING
    timestamp: str


class NDVIMetadata(BaseModel):
    """Metadata about the satellite imagery source."""
    satellite_source: str = "mock"
    scene_date: Optional[str] = None
    cloud_cover: Optional[float] = None


class NDVIAnalysis(BaseModel):
    """Complete NDVI analysis result."""
    tiff_url: str
    png_url: Optional[str] = "placeholder"  # False color composite
    stats: NDVIStats
    metadata: Optional[NDVIMetadata] = None


class FieldResponse(BaseModel):
    """API response for a farm field."""
    id: str
    owner_id: str
    name: str
    boundary: dict  # GeoJSON
    crop_type: Optional[str] = None
    planting_date: Optional[datetime] = None
    area_acres: float
    latest_analysis: Optional[NDVIAnalysis] = None
    analysis_history: Optional[List[NDVIAnalysis]] = []
    
    class Config:
        from_attributes = True