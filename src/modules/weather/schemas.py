"""
Pydantic schemas for weather API responses.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class WeatherConditionResponse(BaseModel):
    """Current weather conditions."""
    temperature: float = Field(..., description="Temperature in Celsius")
    feels_like: float = Field(..., description="Feels like temperature")
    humidity: int = Field(..., description="Humidity percentage (0-100)")
    pressure: int = Field(..., description="Atmospheric pressure in hPa")
    wind_speed: float = Field(..., description="Wind speed in m/s")
    wind_direction: int = Field(..., description="Wind direction in degrees")
    clouds: int = Field(..., description="Cloud cover percentage")
    description: str = Field(..., description="Weather description")
    icon: str = Field(..., description="Weather icon code")
    timestamp: datetime = Field(..., description="Observation time")
    
    class Config:
        from_attributes = True


class DailyForecastResponse(BaseModel):
    """Daily weather forecast."""
    date: datetime = Field(..., description="Forecast date")
    temp_min: float = Field(..., description="Minimum temperature")
    temp_max: float = Field(..., description="Maximum temperature")
    humidity: int = Field(..., description="Average humidity")
    wind_speed: float = Field(..., description="Average wind speed")
    description: str = Field(..., description="Weather description")
    icon: str = Field(..., description="Weather icon code")
    pop: float = Field(..., description="Probability of precipitation (0-1)")
    
    class Config:
        from_attributes = True


class AgriculturalInsights(BaseModel):
    """Agricultural insights based on weather."""
    irrigation_needed: bool = Field(..., description="Whether irrigation is recommended")
    spray_conditions: str = Field(..., description="Spray conditions: good, moderate, poor")
    frost_risk: bool = Field(..., description="Frost risk in forecast")
    heat_stress_risk: bool = Field(..., description="Heat stress risk in forecast")
    recommendations: List[str] = Field(default=[], description="Farming recommendations")


class WeatherResponse(BaseModel):
    """Complete weather response for a farm."""
    farm_id: str
    farm_name: str
    location: dict = Field(..., description="Farm centroid coordinates")
    current: WeatherConditionResponse
    forecast: List[DailyForecastResponse] = []
    insights: Optional[AgriculturalInsights] = None
