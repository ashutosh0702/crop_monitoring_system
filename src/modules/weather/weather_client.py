"""
OpenWeatherMap API client for hyper-local weather data.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class WeatherCondition:
    """Current weather conditions."""
    temperature: float  # Celsius
    feels_like: float
    humidity: int  # Percentage
    pressure: int  # hPa
    wind_speed: float  # m/s
    wind_direction: int  # degrees
    clouds: int  # Percentage
    description: str
    icon: str
    timestamp: datetime


@dataclass
class DailyForecast:
    """Daily weather forecast."""
    date: datetime
    temp_min: float
    temp_max: float
    humidity: int
    wind_speed: float
    description: str
    icon: str
    pop: float  # Probability of precipitation


@dataclass
class WeatherAlert:
    """Weather alert/warning."""
    event: str
    sender: str
    start: datetime
    end: datetime
    description: str


class OpenWeatherMapClient:
    """
    Client for OpenWeatherMap API.
    
    Free tier includes:
    - Current weather
    - 5-day/3-hour forecast
    - 1000 calls/day
    """
    
    BASE_URL = "https://api.openweathermap.org/data/2.5"
    ONE_CALL_URL = "https://api.openweathermap.org/data/3.0/onecall"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize weather client.
        
        Args:
            api_key: OpenWeatherMap API key. If None, uses settings.
        """
        self.api_key = api_key or settings.OPENWEATHERMAP_API_KEY
        self._client = httpx.AsyncClient(timeout=30.0)
        
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()
    
    async def _make_request(self, url: str, params: dict) -> Optional[dict]:
        """Make API request with error handling."""
        params["appid"] = self.api_key
        params["units"] = "metric"  # Celsius
        
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Weather API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Weather API request failed: {e}")
            return None
    
    async def get_current_weather(
        self,
        lat: float,
        lon: float
    ) -> Optional[WeatherCondition]:
        """
        Get current weather conditions for a location.
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            WeatherCondition object or None on error
        """
        # Check for placeholder API key
        if self.api_key == "placeholder":
            return self._mock_current_weather()
        
        url = f"{self.BASE_URL}/weather"
        params = {"lat": lat, "lon": lon}
        
        data = await self._make_request(url, params)
        if not data:
            return self._mock_current_weather()
        
        return WeatherCondition(
            temperature=data["main"]["temp"],
            feels_like=data["main"]["feels_like"],
            humidity=data["main"]["humidity"],
            pressure=data["main"]["pressure"],
            wind_speed=data["wind"]["speed"],
            wind_direction=data["wind"].get("deg", 0),
            clouds=data["clouds"]["all"],
            description=data["weather"][0]["description"],
            icon=data["weather"][0]["icon"],
            timestamp=datetime.utcnow(),
        )
    
    async def get_forecast(
        self,
        lat: float,
        lon: float,
        days: int = 5
    ) -> List[DailyForecast]:
        """
        Get weather forecast for a location.
        
        Args:
            lat: Latitude
            lon: Longitude
            days: Number of days (max 5 for free tier)
            
        Returns:
            List of DailyForecast objects
        """
        # Check for placeholder API key
        if self.api_key == "placeholder":
            return self._mock_forecast(days)
        
        url = f"{self.BASE_URL}/forecast"
        params = {"lat": lat, "lon": lon, "cnt": days * 8}  # 3-hour intervals
        
        data = await self._make_request(url, params)
        if not data:
            return self._mock_forecast(days)
        
        # Aggregate 3-hour forecasts into daily
        daily_data: Dict[str, List[dict]] = {}
        for item in data.get("list", []):
            date = datetime.fromtimestamp(item["dt"]).date().isoformat()
            if date not in daily_data:
                daily_data[date] = []
            daily_data[date].append(item)
        
        forecasts = []
        for date_str, items in list(daily_data.items())[:days]:
            temps = [i["main"]["temp"] for i in items]
            humidities = [i["main"]["humidity"] for i in items]
            wind_speeds = [i["wind"]["speed"] for i in items]
            pops = [i.get("pop", 0) for i in items]
            
            forecasts.append(DailyForecast(
                date=datetime.fromisoformat(date_str),
                temp_min=min(temps),
                temp_max=max(temps),
                humidity=int(sum(humidities) / len(humidities)),
                wind_speed=sum(wind_speeds) / len(wind_speeds),
                description=items[len(items)//2]["weather"][0]["description"],
                icon=items[len(items)//2]["weather"][0]["icon"],
                pop=max(pops),
            ))
        
        return forecasts
    
    async def get_historical(
        self,
        lat: float,
        lon: float,
        date: datetime
    ) -> Optional[WeatherCondition]:
        """
        Get historical weather data.
        
        Note: Historical data requires paid subscription.
        Returns mock data for free tier.
        """
        # Historical data requires One Call API 3.0 (paid)
        logger.info("Historical weather requires paid API subscription, returning mock data")
        return self._mock_current_weather()
    
    def get_agricultural_insights(
        self,
        current: WeatherCondition,
        forecast: List[DailyForecast]
    ) -> Dict[str, Any]:
        """
        Generate agricultural insights based on weather data.
        
        Args:
            current: Current weather conditions
            forecast: Weather forecast
            
        Returns:
            Dictionary with farming recommendations
        """
        insights = {
            "irrigation_needed": False,
            "spray_conditions": "unknown",
            "frost_risk": False,
            "heat_stress_risk": False,
            "recommendations": [],
        }
        
        # Irrigation assessment
        if current.humidity < 40 and current.temperature > 25:
            insights["irrigation_needed"] = True
            insights["recommendations"].append(
                "Low humidity and high temperature - consider irrigation"
            )
        
        # Check forecast for rain
        rain_expected = any(f.pop > 0.5 for f in forecast[:3])
        if rain_expected:
            insights["irrigation_needed"] = False
            insights["recommendations"].append(
                "Rain expected in next 3 days - delay irrigation"
            )
        
        # Spray conditions (wind, rain)
        if current.wind_speed < 3 and not rain_expected:
            insights["spray_conditions"] = "good"
        elif current.wind_speed > 5:
            insights["spray_conditions"] = "poor"
            insights["recommendations"].append(
                "High wind - avoid pesticide/herbicide application"
            )
        else:
            insights["spray_conditions"] = "moderate"
        
        # Frost risk (for forecast)
        if any(f.temp_min < 2 for f in forecast):
            insights["frost_risk"] = True
            insights["recommendations"].append(
                "Frost risk detected - protect sensitive crops"
            )
        
        # Heat stress
        if any(f.temp_max > 35 for f in forecast):
            insights["heat_stress_risk"] = True
            insights["recommendations"].append(
                "Heat stress risk - ensure adequate irrigation"
            )
        
        return insights
    
    def _mock_current_weather(self) -> WeatherCondition:
        """Generate mock weather data for development."""
        return WeatherCondition(
            temperature=28.5,
            feels_like=30.2,
            humidity=65,
            pressure=1015,
            wind_speed=3.5,
            wind_direction=180,
            clouds=40,
            description="partly cloudy",
            icon="02d",
            timestamp=datetime.utcnow(),
        )
    
    def _mock_forecast(self, days: int = 5) -> List[DailyForecast]:
        """Generate mock forecast data for development."""
        forecasts = []
        base_date = datetime.utcnow().date()
        
        for i in range(days):
            forecasts.append(DailyForecast(
                date=datetime.combine(base_date + timedelta(days=i), datetime.min.time()),
                temp_min=22 + i,
                temp_max=32 + i,
                humidity=60 - i * 2,
                wind_speed=2.5 + i * 0.5,
                description="partly cloudy" if i % 2 == 0 else "light rain",
                icon="02d" if i % 2 == 0 else "10d",
                pop=0.1 if i % 2 == 0 else 0.6,
            ))
        
        return forecasts


# Singleton instance
_weather_client: Optional[OpenWeatherMapClient] = None


def get_weather_client() -> OpenWeatherMapClient:
    """Get or create weather client singleton."""
    global _weather_client
    if _weather_client is None:
        _weather_client = OpenWeatherMapClient()
    return _weather_client
