"""
NDVI Analysis Service with STAC API integration.
Supports real Sentinel-2 imagery streaming and fallback to mock data.
"""

import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import shape

from src.config import settings

logger = logging.getLogger(__name__)


class NDVILogic:
    """
    NDVI calculation and analysis service.
    
    Modes:
    - Production: Fetches real Sentinel-2 data via STAC API
    - Development: Uses mock random data for testing
    """
    
    def __init__(self, use_mock: bool = True):
        """
        Initialize NDVI service.
        
        Args:
            use_mock: If True, use mock data instead of real satellite imagery.
                     Set to False for production with real STAC API access.
        """
        self.use_mock = use_mock
        
        # Ensure storage directories exist
        self.tiff_storage = settings.TIFF_STORAGE_PATH
        self.png_storage = settings.PNG_STORAGE_PATH
        self.tiff_storage.mkdir(parents=True, exist_ok=True)
        self.png_storage.mkdir(parents=True, exist_ok=True)
        
        # Initialize STAC client (lazy import to avoid issues)
        self._stac_client = None
        
    @property
    def stac_client(self):
        """Lazy load STAC client."""
        if self._stac_client is None:
            from src.modules.crops.stac_client import get_stac_client
            self._stac_client = get_stac_client(use_mock=self.use_mock)
        return self._stac_client
    
    def calculate_ndvi_stats(self, ndvi_array: np.ndarray) -> Dict[str, Any]:
        """
        Calculate comprehensive NDVI statistics.
        
        Args:
            ndvi_array: NDVI values array
            
        Returns:
            Dictionary with mean, min, max, std, and status classification
        """
        # Filter out NoData values
        valid_ndvi = ndvi_array[~np.isnan(ndvi_array)]
        
        if valid_ndvi.size == 0:
            return {
                "mean_ndvi": 0.0,
                "min_ndvi": None,
                "max_ndvi": None,
                "std_ndvi": None,
                "status": "DATA_MISSING"
            }
        
        mean_val = float(np.mean(valid_ndvi))
        min_val = float(np.min(valid_ndvi))
        max_val = float(np.max(valid_ndvi))
        std_val = float(np.std(valid_ndvi))
        
        # Classification based on mean NDVI
        if mean_val >= 0.50:
            status = "HEALTHY"
        elif mean_val >= 0.25:
            status = "MODERATE"
        else:
            status = "CRITICAL"
            
        return {
            "mean_ndvi": mean_val,
            "min_ndvi": min_val,
            "max_ndvi": max_val,
            "std_ndvi": std_val,
            "status": status
        }
    
    async def process_field_ndvi(
        self,
        user_id: str,
        farm_id: str,
        geojson_boundary: dict
    ) -> Dict[str, Any]:
        """
        Process NDVI for a farm field.
        
        1. Fetches Red/NIR bands (real via STAC or mock)
        2. Calculates NDVI
        3. Saves GeoTIFF to storage
        4. Creates false color composite PNG
        5. Returns analysis results
        
        Args:
            user_id: UUID of the user
            farm_id: UUID of the farm
            geojson_boundary: GeoJSON Polygon of farm boundary
            
        Returns:
            Dictionary with tiff_url, png_url, and stats
        """
        # Convert GeoJSON to Shapely for processing
        polygon_geom = shape(geojson_boundary)
        bounds = polygon_geom.bounds  # (minx, miny, maxx, maxy)
        
        # Generate unique filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"{user_id}_{farm_id}_{timestamp}"
        tiff_path = self.tiff_storage / f"{base_filename}.tif"
        png_path = self.png_storage / f"{base_filename}.png"
        
        # Variables to store scene metadata
        satellite_source = "mock"
        scene_date = None
        cloud_cover = None
        
        if self.use_mock:
            # --- MOCK MODE: Generate synthetic data ---
            logger.info(f"Using MOCK data for farm {farm_id}")
            red_band, nir_band, green_band = self._generate_mock_bands()
        else:
            # --- PRODUCTION MODE: Fetch from STAC API ---
            logger.info(f"Fetching Sentinel-2 data for farm {farm_id}")
            
            try:
                # Search for available scenes
                scenes = self.stac_client.search_scenes(
                    geometry=geojson_boundary,
                    max_cloud_cover=30.0,
                    limit=3
                )
                
                if not scenes:
                    logger.warning("No scenes found, falling back to mock data")
                    red_band, nir_band, green_band = self._generate_mock_bands()
                else:
                    scene = scenes[0]  # Best scene (lowest cloud cover)
                    satellite_source = "sentinel-2"
                    scene_date = scene.datetime
                    cloud_cover = scene.cloud_cover
                    
                    logger.info(f"Using scene {scene.id} from {scene.datetime}")
                    
                    # Stream and mask bands
                    red_band = self.stac_client.stream_and_mask_band(
                        scene.red_band_url, geojson_boundary
                    )
                    nir_band = self.stac_client.stream_and_mask_band(
                        scene.nir_band_url, geojson_boundary
                    )
                    green_band = self.stac_client.stream_and_mask_band(
                        scene.green_band_url, geojson_boundary
                    ) if scene.green_band_url else None
                    
                    if red_band is None or nir_band is None:
                        logger.error("Failed to stream bands, falling back to mock")
                        red_band, nir_band, green_band = self._generate_mock_bands()
                        satellite_source = "mock"
                        
            except Exception as e:
                logger.error(f"STAC API error: {e}, falling back to mock data")
                red_band, nir_band, green_band = self._generate_mock_bands()
        
        # --- NDVI CALCULATION ---
        ndvi = self._calculate_ndvi(nir_band, red_band)
        
        # --- SAVE GEOTIFF ---
        self._save_geotiff(ndvi, bounds, tiff_path)
        logger.info(f"Saved NDVI GeoTIFF to {tiff_path}")
        
        # --- CREATE FALSE COLOR COMPOSITE ---
        if green_band is not None:
            self.stac_client.create_false_color_composite(
                nir_band, red_band, green_band, str(png_path)
            )
            png_url = str(png_path)
        else:
            # Create simple NDVI visualization if no green band
            self._save_ndvi_png(ndvi, str(png_path))
            png_url = str(png_path)
        
        # --- CALCULATE STATS ---
        stats = self.calculate_ndvi_stats(ndvi)
        stats["timestamp"] = datetime.now().isoformat()
        
        return {
            "tiff_url": str(tiff_path),
            "png_url": png_url,
            "stats": stats,
            "metadata": {
                "satellite_source": satellite_source,
                "scene_date": scene_date.isoformat() if scene_date else None,
                "cloud_cover": cloud_cover,
            }
        }
    
    def _generate_mock_bands(self, size: tuple = (100, 100)) -> tuple:
        """Generate mock band data for testing."""
        # Simulate vegetation reflectance patterns
        red_band = np.random.uniform(0.02, 0.15, size)  # Low in healthy vegetation
        nir_band = np.random.uniform(0.35, 0.75, size)  # High in healthy vegetation
        green_band = np.random.uniform(0.05, 0.20, size)  # Moderate
        return red_band, nir_band, green_band
    
    def _calculate_ndvi(self, nir: np.ndarray, red: np.ndarray) -> np.ndarray:
        """Calculate NDVI from NIR and Red bands."""
        with np.errstate(divide='ignore', invalid='ignore'):
            denom = nir.astype(float) + red.astype(float)
            ndvi = np.where(denom == 0, 0, (nir - red) / denom)
        return ndvi
    
    def _save_geotiff(
        self,
        ndvi: np.ndarray,
        bounds: tuple,
        file_path: Path
    ) -> None:
        """Save NDVI array as GeoTIFF."""
        transform = from_bounds(*bounds, ndvi.shape[1], ndvi.shape[0])
        
        with rasterio.open(
            file_path, 'w',
            driver='GTiff',
            height=ndvi.shape[0],
            width=ndvi.shape[1],
            count=1,
            dtype=ndvi.dtype,
            crs='EPSG:4326',
            transform=transform
        ) as dst:
            dst.write(ndvi, 1)
    
    def _save_ndvi_png(self, ndvi: np.ndarray, file_path: str) -> None:
        """Save NDVI as a colored PNG visualization."""
        try:
            import matplotlib.pyplot as plt
            from matplotlib import colors
            
            # Create custom colormap (red -> yellow -> green)
            cmap = colors.LinearSegmentedColormap.from_list(
                'ndvi', ['brown', 'yellow', 'green']
            )
            
            # Normalize to 0-1 range
            ndvi_norm = np.clip((ndvi + 1) / 2, 0, 1)  # NDVI is -1 to 1
            
            plt.figure(figsize=(10, 10))
            plt.imshow(ndvi_norm, cmap=cmap)
            plt.colorbar(label='NDVI')
            plt.axis('off')
            plt.savefig(file_path, bbox_inches='tight', dpi=100)
            plt.close()
            
        except Exception as e:
            logger.error(f"Failed to save NDVI PNG: {e}")
            # Create placeholder image
            from PIL import Image
            img = Image.new('RGB', (100, 100), color=(100, 150, 50))
            img.save(file_path, 'PNG')