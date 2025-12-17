from pydantic import BaseModel, Field, validator
from typing import List, Literal

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
    # Note: Triple nested list -> [ [ [lng, lat], ... ] ]
    # Level 1: The Polygon (can have holes)
    # Level 2: The Linear Ring (the boundary)
    # Level 3: The Coordinate Pair [Longitude, Latitude]
    coordinates: List[List[List[float]]]

    @validator("coordinates")
    def validate_polygon_closure(cls, v):
        if not v:
            raise ValueError("Polygon must have at least one linear ring (boundary).")
        
        outer_ring = v[0]
        if len(outer_ring) < 4:
            raise ValueError("A Polygon LinearRing must have at least 4 points.")
        
        # GeoJSON Rule: The first and last point must be identical to close the shape
        if outer_ring[0] != outer_ring[-1]:
            raise ValueError("The first and last coordinates must be the same to close the polygon.")
        
        return v

# --- 2. API Models ---

class FieldCreate(BaseModel):
    name: str = Field(..., example="North River Field")
    boundary: GeoJSONPolygon

class FieldResponse(FieldCreate):
    id: str
    owner_id: str
    area_acres: float