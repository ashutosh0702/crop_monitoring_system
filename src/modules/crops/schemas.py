"""
Pydantic schemas for crop indices API responses.
"""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class IndexResult(BaseModel):
    """Single index calculation result."""
    index_name: str = Field(..., description="Index name: NDVI, NDWI, EVI, SAVI, NDRE")
    mean: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    std: Optional[float] = None
    status: str = Field(..., description="Status classification based on index value")


class IndicesSummary(BaseModel):
    """Summary of crop health based on all indices."""
    overall_health: str = Field(..., description="GOOD, MODERATE, POOR")
    moisture_status: str = Field(..., description="ADEQUATE, STRESSED")
    vegetation_density: str = Field(..., description="HIGH, MODERATE, LOW")
    recommendations: List[str] = Field(default_factory=list)


class AllIndicesResponse(BaseModel):
    """Response containing all calculated indices."""
    id: Optional[str] = None
    farm_id: str
    timestamp: datetime
    scene_date: datetime
    indices: Dict[str, IndexResult]
    summary: IndicesSummary
    source: str = Field(..., description="Data source: mock, sentinel-2")
    stack_tiff_url: str = Field(..., description="Path or URL to the multi-band GeoTIFF stack")
    band_order: List[str] = Field(default_factory=list, description="Band order inside the stack GeoTIFF")
    cloud_cover: Optional[float] = None


class NDMIResponse(BaseModel):
    """NDMI-specific response."""
    farm_id: str
    timestamp: datetime
    scene_date: datetime
    ndmi: IndexResult
    moisture_recommendations: List[str] = Field(default_factory=list)
    stack_tiff_url: str


class EVIResponse(BaseModel):
    """EVI-specific response."""
    farm_id: str
    timestamp: datetime
    scene_date: datetime
    evi: IndexResult
    vegetation_analysis: str
    stack_tiff_url: str
