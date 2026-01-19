"""
Weather router for farm-specific weather data.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import List
from dataclasses import asdict

from src.database import get_db
from src.models import User, Farm
from src.modules.weather.weather_client import get_weather_client
from src.modules.weather import schemas

from geoalchemy2.shape import to_shape


router = APIRouter(prefix="/weather", tags=["Weather"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token."""
    from src.core import security
    
    try:
        payload = security.jwt.decode(
            token,
            security.settings.SECRET_KEY,
            algorithms=[security.settings.ALGORITHM]
        )
        phone = payload.get("sub")
        if phone is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.phone_number == phone).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


def get_farm_centroid(farm: Farm) -> tuple:
    """Get the centroid coordinates of a farm boundary."""
    shapely_geom = to_shape(farm.boundary)
    centroid = shapely_geom.centroid
    return centroid.y, centroid.x  # lat, lon


@router.get("/current/{farm_id}", response_model=schemas.WeatherConditionResponse)
async def get_current_weather(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get current weather conditions for a farm location.
    
    Uses the farm's centroid coordinates for hyper-local weather.
    """
    # Get farm and verify ownership
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == current_user.id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    # Get coordinates from farm centroid
    lat, lon = get_farm_centroid(farm)
    
    # Fetch weather
    client = get_weather_client()
    weather = await client.get_current_weather(lat, lon)
    
    if not weather:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weather service unavailable"
        )
    
    return asdict(weather)


@router.get("/forecast/{farm_id}", response_model=List[schemas.DailyForecastResponse])
async def get_weather_forecast(
    farm_id: str,
    days: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get weather forecast for a farm location.
    
    - **farm_id**: Farm UUID
    - **days**: Number of forecast days (1-5, default 5)
    """
    # Validate days
    days = min(max(days, 1), 5)
    
    # Get farm and verify ownership
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == current_user.id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    lat, lon = get_farm_centroid(farm)
    
    client = get_weather_client()
    forecast = await client.get_forecast(lat, lon, days)
    
    return [asdict(f) for f in forecast]


@router.get("/full/{farm_id}", response_model=schemas.WeatherResponse)
async def get_full_weather(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get complete weather data for a farm including agricultural insights.
    
    Returns:
    - Current conditions
    - 5-day forecast
    - Farming recommendations (irrigation, spray conditions, frost/heat risks)
    """
    # Get farm and verify ownership
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == current_user.id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    lat, lon = get_farm_centroid(farm)
    
    client = get_weather_client()
    
    # Fetch current and forecast
    current = await client.get_current_weather(lat, lon)
    forecast = await client.get_forecast(lat, lon, 5)
    
    if not current:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weather service unavailable"
        )
    
    # Generate agricultural insights
    insights = client.get_agricultural_insights(current, forecast)
    
    return {
        "farm_id": str(farm.id),
        "farm_name": farm.name,
        "location": {"lat": lat, "lon": lon},
        "current": asdict(current),
        "forecast": [asdict(f) for f in forecast],
        "insights": insights,
    }


@router.get("/insights/{farm_id}", response_model=schemas.AgriculturalInsights)
async def get_weather_insights(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get agricultural insights and recommendations based on weather.
    
    Includes:
    - Irrigation recommendations
    - Spray conditions
    - Frost/heat stress warnings
    - Farming recommendations
    """
    # Get farm and verify ownership
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == current_user.id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    lat, lon = get_farm_centroid(farm)
    
    client = get_weather_client()
    
    current = await client.get_current_weather(lat, lon)
    forecast = await client.get_forecast(lat, lon, 5)
    
    if not current:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Weather service unavailable"
        )
    
    return client.get_agricultural_insights(current, forecast)
