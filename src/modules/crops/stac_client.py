"""
STAC API Client for free Sentinel-2 imagery from AWS Open Data Registry.
Uses Element84's Earth Search API and rasterio for COG streaming.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds
from shapely.geometry import shape, mapping
from pystac_client import Client as STACClient
from PIL import Image
import io

logger = logging.getLogger(__name__)


@dataclass
class SentinelScene:
    """Represents a Sentinel-2 scene with band URLs."""
    id: str
    datetime: datetime
    cloud_cover: float
    red_band_url: str  # B04
    nir_band_url: str  # B08
    green_band_url: Optional[str] = None  # B03 for false color
    blue_band_url: Optional[str] = None  # B02 for false color
    bbox: Optional[List[float]] = None


class STACImageryClient:
    """
    Client for fetching Sentinel-2 imagery via STAC API.
    Uses Element84's Earth Search (free, no API key required).
    """
    
    # Earth Search STAC API endpoint (Element84)
    EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1"
    
    # Sentinel-2 collection
    SENTINEL2_COLLECTION = "sentinel-2-l2a"
    
    def __init__(self, stac_url: Optional[str] = None):
        """
        Initialize STAC client.
        
        Args:
            stac_url: Optional custom STAC API URL. Defaults to Earth Search.
        """
        self.stac_url = stac_url or self.EARTH_SEARCH_URL
        self.client = STACClient.open(self.stac_url)
        
    def search_scenes(
        self,
        geometry: dict,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_cloud_cover: float = 30.0,
        limit: int = 5
    ) -> List[SentinelScene]:
        """
        Search for Sentinel-2 scenes covering the given geometry.
        
        Args:
            geometry: GeoJSON geometry (Polygon or MultiPolygon)
            start_date: Start of date range (defaults to 30 days ago)
            end_date: End of date range (defaults to today)
            max_cloud_cover: Maximum cloud cover percentage
            limit: Maximum number of scenes to return
            
        Returns:
            List of SentinelScene objects sorted by cloud cover (ascending)
        """
        # Default date range: last 30 days
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=30)
            
        date_range = f"{start_date.strftime('%Y-%m-%d')}/{end_date.strftime('%Y-%m-%d')}"
        
        logger.info(f"Searching STAC for scenes: {date_range}, cloud cover < {max_cloud_cover}%")
        
        try:
            search = self.client.search(
                collections=[self.SENTINEL2_COLLECTION],
                intersects=geometry,
                datetime=date_range,
                query={"eo:cloud_cover": {"lt": max_cloud_cover}},
                sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
                max_items=limit,
            )
            
            scenes = []
            for item in search.items():
                scene = self._parse_item(item)
                if scene:
                    scenes.append(scene)
                    
            logger.info(f"Found {len(scenes)} scenes matching criteria")
            return scenes
            
        except Exception as e:
            logger.error(f"STAC search failed: {e}")
            return []
    
    def _parse_item(self, item) -> Optional[SentinelScene]:
        """Parse a STAC item into a SentinelScene object."""
        try:
            assets = item.assets
            
            # Get band URLs - Sentinel-2 L2A uses these asset keys
            red_asset = assets.get("red") or assets.get("B04")
            nir_asset = assets.get("nir") or assets.get("B08")
            green_asset = assets.get("green") or assets.get("B03")
            blue_asset = assets.get("blue") or assets.get("B02")
            
            if not red_asset or not nir_asset:
                logger.warning(f"Missing required bands for item {item.id}")
                return None
                
            return SentinelScene(
                id=item.id,
                datetime=item.datetime,
                cloud_cover=item.properties.get("eo:cloud_cover", 0),
                red_band_url=red_asset.href,
                nir_band_url=nir_asset.href,
                green_band_url=green_asset.href if green_asset else None,
                blue_band_url=blue_asset.href if blue_asset else None,
                bbox=item.bbox,
            )
        except Exception as e:
            logger.error(f"Failed to parse STAC item: {e}")
            return None
    
    def stream_and_mask_band(
        self,
        band_url: str,
        geometry: dict,
        resolution: Tuple[int, int] = (100, 100)
    ) -> Optional[np.ndarray]:
        """
        Stream a COG band and mask it to the given geometry.
        Does NOT download the full tile - uses HTTP range requests.
        
        Args:
            band_url: URL to the COG band file
            geometry: GeoJSON geometry to mask to
            resolution: Output resolution (height, width)
            
        Returns:
            Masked numpy array or None on failure
        """
        try:
            # Use GDAL vsicurl for streaming
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', 
                             CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif'):
                with rasterio.open(band_url) as src:
                    # Create shapely geometry for masking
                    geom = shape(geometry)
                    
                    # Mask the raster to our geometry
                    out_image, out_transform = mask(
                        src, 
                        [mapping(geom)], 
                        crop=True,
                        nodata=np.nan
                    )
                    
                    # Return the first band
                    return out_image[0]
                    
        except Exception as e:
            logger.error(f"Failed to stream band {band_url}: {e}")
            return None
    
    def calculate_ndvi(
        self,
        red_array: np.ndarray,
        nir_array: np.ndarray
    ) -> np.ndarray:
        """
        Calculate NDVI from Red and NIR bands.
        
        NDVI = (NIR - Red) / (NIR + Red)
        
        Args:
            red_array: Red band array (B04)
            nir_array: NIR band array (B08)
            
        Returns:
            NDVI array with values between -1 and 1
        """
        # Avoid division by zero
        with np.errstate(divide='ignore', invalid='ignore'):
            ndvi = (nir_array.astype(float) - red_array.astype(float)) / \
                   (nir_array.astype(float) + red_array.astype(float))
            
        # Handle nodata
        ndvi = np.where(np.isfinite(ndvi), ndvi, np.nan)
        
        return ndvi
    
    def create_false_color_composite(
        self,
        nir_array: np.ndarray,
        red_array: np.ndarray,
        green_array: np.ndarray,
        output_path: str
    ) -> bool:
        """
        Create a false color composite PNG (NIR-Red-Green).
        Useful for visualizing vegetation health.
        
        Args:
            nir_array: NIR band array
            red_array: Red band array
            green_array: Green band array
            output_path: Path to save the PNG
            
        Returns:
            True on success
        """
        try:
            # Normalize arrays to 0-255
            def normalize(arr):
                arr = np.nan_to_num(arr, nan=0)
                arr_min, arr_max = np.percentile(arr, [2, 98])
                arr = np.clip((arr - arr_min) / (arr_max - arr_min) * 255, 0, 255)
                return arr.astype(np.uint8)
            
            r = normalize(nir_array)
            g = normalize(red_array)
            b = normalize(green_array)
            
            # Stack into RGB
            rgb = np.dstack([r, g, b])
            
            # Save as PNG
            img = Image.fromarray(rgb)
            img.save(output_path, 'PNG')
            
            logger.info(f"Saved false color composite to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create false color composite: {e}")
            return False


# Fallback mock client for development/testing
class MockSTACClient:
    """
    Mock STAC client for development when no internet or for testing.
    Returns synthetic data matching the real client interface.
    """
    
    def search_scenes(self, geometry: dict, **kwargs) -> List[SentinelScene]:
        """Return a mock scene."""
        return [
            SentinelScene(
                id="mock-scene-001",
                datetime=datetime.utcnow() - timedelta(days=3),
                cloud_cover=5.0,
                red_band_url="mock://sentinel-2/B04.tif",
                nir_band_url="mock://sentinel-2/B08.tif",
                green_band_url="mock://sentinel-2/B03.tif",
                blue_band_url="mock://sentinel-2/B02.tif",
            )
        ]
    
    def stream_and_mask_band(
        self,
        band_url: str,
        geometry: dict,
        resolution: Tuple[int, int] = (100, 100)
    ) -> np.ndarray:
        """Return mock band data."""
        if "B04" in band_url or "red" in band_url.lower():
            # Red band - lower reflectance in vegetation
            return np.random.uniform(0.02, 0.08, resolution)
        else:
            # NIR band - higher reflectance in vegetation
            return np.random.uniform(0.3, 0.6, resolution)
    
    def calculate_ndvi(
        self,
        red_array: np.ndarray,
        nir_array: np.ndarray
    ) -> np.ndarray:
        """Calculate NDVI (same logic as real client)."""
        with np.errstate(divide='ignore', invalid='ignore'):
            ndvi = (nir_array.astype(float) - red_array.astype(float)) / \
                   (nir_array.astype(float) + red_array.astype(float))
        return np.where(np.isfinite(ndvi), ndvi, np.nan)
    
    def create_false_color_composite(
        self,
        nir_array: np.ndarray,
        red_array: np.ndarray,
        green_array: np.ndarray,
        output_path: str
    ) -> bool:
        """Create a mock false color composite."""
        try:
            # Create a simple gradient image for mock
            h, w = nir_array.shape
            img = Image.new('RGB', (w, h), color=(100, 150, 50))
            img.save(output_path, 'PNG')
            return True
        except:
            return False


def get_stac_client(use_mock: bool = False) -> STACImageryClient:
    """
    Factory function to get appropriate STAC client.
    
    Args:
        use_mock: If True, return mock client for testing
        
    Returns:
        STAC client instance
    """
    if use_mock:
        return MockSTACClient()
    return STACImageryClient()
