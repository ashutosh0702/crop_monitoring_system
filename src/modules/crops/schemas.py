"""
Pydantic schemas for crop indices API responses.
"""

from datetime import datetime
from typing import Optional, Dict, List, Any
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
    recommendations: List[str] = []


class AllIndicesResponse(BaseModel):
    """Response containing all calculated indices."""
    farm_id: str
    timestamp: datetime
    indices: Dict[str, IndexResult]
    summary: IndicesSummary
    source: str = Field(..., description="Data source: mock, sentinel-2")


class NDWIResponse(BaseModel):
    """NDWI-specific response."""
    farm_id: str
    timestamp: datetime
    ndwi: IndexResult
    moisture_recommendations: List[str] = []


class EVIResponse(BaseModel):
    """EVI-specific response."""
    farm_id: str
    timestamp: datetime
    evi: IndexResult
    vegetation_analysis: str
