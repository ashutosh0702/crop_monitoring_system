"""
Pydantic schemas for alerts API.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class AlertResponse(BaseModel):
    """Alert response model."""
    id: str
    farm_id: str
    farm_name: Optional[str] = None
    alert_type: str = Field(..., description="NDVI_DROP, WEATHER_WARNING, etc.")
    severity: str = Field(..., description="LOW, MEDIUM, HIGH, CRITICAL")
    message: str
    is_read: bool = False
    created_at: datetime
    
    class Config:
        from_attributes = True


class AlertMarkReadRequest(BaseModel):
    """Request to mark alert as read."""
    alert_ids: List[str]


class AlertSummary(BaseModel):
    """Summary of user's alerts."""
    total: int
    unread: int
    by_severity: dict  # {"HIGH": 2, "MEDIUM": 1, etc.}
