"""
Advanced Agricultural Indices Service.
Calculates NDWI, EVI, and other vegetation/moisture indices.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

import numpy as np

from src.config import settings

logger = logging.getLogger(__name__)


class IndicesService:
    """
    Service for calculating advanced agricultural indices.
    
    Supported Indices:
    - NDWI: Normalized Difference Water Index (moisture monitoring)
    - EVI: Enhanced Vegetation Index (dense vegetation)
    - SAVI: Soil Adjusted Vegetation Index
    - NDRE: Normalized Difference Red Edge (chlorophyll content)
    """
    
    def __init__(self, use_mock: bool = True):
        """
        Initialize indices service.
        
        Args:
            use_mock: Use mock data instead of real satellite bands
        """
        self.use_mock = use_mock
        self.output_dir = settings.TIFF_STORAGE_PATH
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def calculate_ndwi(
        self,
        nir_band: np.ndarray,
        swir_band: np.ndarray
    ) -> np.ndarray:
        """
        Calculate Normalized Difference Water Index (NDWI).
        
        NDWI = (NIR - SWIR) / (NIR + SWIR)
        
        Interpretation:
        - High values (>0.3): High water content, healthy vegetation
        - Low/negative values: Water stress, dry conditions
        
        Args:
            nir_band: Near-infrared band (Sentinel-2 B08)
            swir_band: Short-wave infrared band (Sentinel-2 B11)
            
        Returns:
            NDWI array with values from -1 to 1
        """
        with np.errstate(divide='ignore', invalid='ignore'):
            ndwi = (nir_band.astype(float) - swir_band.astype(float)) / \
                   (nir_band.astype(float) + swir_band.astype(float))
            ndwi = np.where(np.isfinite(ndwi), ndwi, 0)
        return ndwi
    
    def calculate_evi(
        self,
        nir_band: np.ndarray,
        red_band: np.ndarray,
        blue_band: np.ndarray,
        gain: float = 2.5,
        c1: float = 6.0,
        c2: float = 7.5,
        l: float = 1.0
    ) -> np.ndarray:
        """
        Calculate Enhanced Vegetation Index (EVI).
        
        EVI = G * ((NIR - RED) / (NIR + C1*RED - C2*BLUE + L))
        
        Better than NDVI for:
        - Dense vegetation (reduces saturation)
        - Areas with significant atmospheric aerosols
        - Canopy background variations
        
        Args:
            nir_band: Near-infrared band (Sentinel-2 B08)
            red_band: Red band (Sentinel-2 B04)
            blue_band: Blue band (Sentinel-2 B02)
            gain: Gain factor (default 2.5)
            c1: Aerosol resistance coefficient (default 6.0)
            c2: Aerosol resistance coefficient (default 7.5)
            l: Canopy background adjustment (default 1.0)
            
        Returns:
            EVI array (typically 0 to 1 for vegetation)
        """
        with np.errstate(divide='ignore', invalid='ignore'):
            nir = nir_band.astype(float)
            red = red_band.astype(float)
            blue = blue_band.astype(float)
            
            denominator = nir + c1 * red - c2 * blue + l
            evi = gain * (nir - red) / denominator
            
            # Clip to reasonable range
            evi = np.clip(evi, -1, 1)
            evi = np.where(np.isfinite(evi), evi, 0)
        
        return evi
    
    def calculate_savi(
        self,
        nir_band: np.ndarray,
        red_band: np.ndarray,
        l: float = 0.5
    ) -> np.ndarray:
        """
        Calculate Soil Adjusted Vegetation Index (SAVI).
        
        SAVI = ((NIR - RED) / (NIR + RED + L)) * (1 + L)
        
        Minimizes soil brightness influences.
        L factor: 0 = high vegetation, 1 = low vegetation
        
        Args:
            nir_band: Near-infrared band
            red_band: Red band
            l: Soil brightness correction factor (default 0.5)
            
        Returns:
            SAVI array
        """
        with np.errstate(divide='ignore', invalid='ignore'):
            nir = nir_band.astype(float)
            red = red_band.astype(float)
            
            savi = ((nir - red) / (nir + red + l)) * (1 + l)
            savi = np.where(np.isfinite(savi), savi, 0)
        
        return savi
    
    def calculate_ndre(
        self,
        nir_band: np.ndarray,
        red_edge_band: np.ndarray
    ) -> np.ndarray:
        """
        Calculate Normalized Difference Red Edge Index (NDRE).
        
        NDRE = (NIR - RedEdge) / (NIR + RedEdge)
        
        Sensitive to chlorophyll content in leaves.
        Better than NDVI for mid-late season crops.
        
        Args:
            nir_band: Near-infrared band (Sentinel-2 B08)
            red_edge_band: Red edge band (Sentinel-2 B05 or B06)
            
        Returns:
            NDRE array
        """
        with np.errstate(divide='ignore', invalid='ignore'):
            nir = nir_band.astype(float)
            red_edge = red_edge_band.astype(float)
            
            ndre = (nir - red_edge) / (nir + red_edge)
            ndre = np.where(np.isfinite(ndre), ndre, 0)
        
        return ndre
    
    def get_index_stats(self, index_array: np.ndarray, index_name: str) -> Dict[str, Any]:
        """
        Calculate statistics for an index array.
        
        Args:
            index_array: The calculated index values
            index_name: Name of the index (NDWI, EVI, etc.)
            
        Returns:
            Dictionary with statistics
        """
        valid_data = index_array[~np.isnan(index_array)]
        
        if valid_data.size == 0:
            return {
                "index_name": index_name,
                "mean": None,
                "min": None,
                "max": None,
                "std": None,
                "status": "NO_DATA"
            }
        
        mean_val = float(np.mean(valid_data))
        
        # Status classification based on index type
        if index_name == "NDWI":
            if mean_val > 0.2:
                status = "ADEQUATE_MOISTURE"
            elif mean_val > 0:
                status = "MODERATE_MOISTURE"
            else:
                status = "LOW_MOISTURE"
        elif index_name == "EVI":
            if mean_val > 0.4:
                status = "DENSE_VEGETATION"
            elif mean_val > 0.2:
                status = "MODERATE_VEGETATION"
            else:
                status = "SPARSE_VEGETATION"
        else:
            status = "CALCULATED"
        
        return {
            "index_name": index_name,
            "mean": round(mean_val, 4),
            "min": round(float(np.min(valid_data)), 4),
            "max": round(float(np.max(valid_data)), 4),
            "std": round(float(np.std(valid_data)), 4),
            "status": status
        }
    
    async def process_all_indices(
        self,
        user_id: str,
        farm_id: str,
        geojson_boundary: dict
    ) -> Dict[str, Any]:
        """
        Process all available indices for a farm.
        
        Args:
            user_id: User UUID
            farm_id: Farm UUID
            geojson_boundary: Farm boundary as GeoJSON
            
        Returns:
            Dictionary with all index results
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if self.use_mock:
            # Generate mock band data
            size = (100, 100)
            nir_band = np.random.uniform(0.3, 0.8, size)
            red_band = np.random.uniform(0.02, 0.15, size)
            blue_band = np.random.uniform(0.01, 0.08, size)
            swir_band = np.random.uniform(0.1, 0.4, size)
            red_edge_band = np.random.uniform(0.1, 0.3, size)
        else:
            # Fetch from STAC API
            from src.modules.crops.stac_client import get_stac_client
            
            client = get_stac_client(use_mock=False)
            scenes = client.search_scenes(
                geometry=geojson_boundary,
                max_cloud_cover=30.0,
                limit=1
            )
            
            if not scenes:
                return {
                    "status": "NO_SATELLITE_DATA",
                    "message": "No satellite imagery found for this location"
                }
            
            scene = scenes[0]
            nir_band = client.stream_and_mask_band(scene.nir_band_url, geojson_boundary)
            red_band = client.stream_and_mask_band(scene.red_band_url, geojson_boundary)
            # Note: Additional bands would need to be added to STAC client
            blue_band = nir_band * 0.1  # Placeholder
            swir_band = nir_band * 0.5  # Placeholder
            red_edge_band = nir_band * 0.7  # Placeholder
        
        # Calculate all indices
        ndvi = self._calculate_ndvi(nir_band, red_band)
        ndwi = self.calculate_ndwi(nir_band, swir_band)
        evi = self.calculate_evi(nir_band, red_band, blue_band)
        savi = self.calculate_savi(nir_band, red_band)
        ndre = self.calculate_ndre(nir_band, red_edge_band)
        
        # Get stats for all
        results = {
            "farm_id": farm_id,
            "timestamp": datetime.now().isoformat(),
            "indices": {
                "NDVI": self.get_index_stats(ndvi, "NDVI"),
                "NDWI": self.get_index_stats(ndwi, "NDWI"),
                "EVI": self.get_index_stats(evi, "EVI"),
                "SAVI": self.get_index_stats(savi, "SAVI"),
                "NDRE": self.get_index_stats(ndre, "NDRE"),
            },
            "summary": self._generate_summary(ndvi, ndwi, evi),
            "source": "mock" if self.use_mock else "sentinel-2"
        }
        
        return results
    
    def _calculate_ndvi(self, nir: np.ndarray, red: np.ndarray) -> np.ndarray:
        """Calculate NDVI for comparison with other indices."""
        with np.errstate(divide='ignore', invalid='ignore'):
            ndvi = (nir.astype(float) - red.astype(float)) / \
                   (nir.astype(float) + red.astype(float))
            ndvi = np.where(np.isfinite(ndvi), ndvi, 0)
        return ndvi
    
    def _generate_summary(
        self,
        ndvi: np.ndarray,
        ndwi: np.ndarray,
        evi: np.ndarray
    ) -> Dict[str, Any]:
        """Generate a summary of vegetation and moisture conditions."""
        ndvi_mean = float(np.nanmean(ndvi))
        ndwi_mean = float(np.nanmean(ndwi))
        evi_mean = float(np.nanmean(evi))
        
        recommendations = []
        
        # Vegetation health
        if ndvi_mean < 0.3:
            recommendations.append("Low vegetation detected - consider crop inspection")
        elif ndvi_mean > 0.6:
            recommendations.append("Dense healthy vegetation - optimal conditions")
        
        # Water stress
        if ndwi_mean < 0:
            recommendations.append("Water stress detected - irrigation recommended")
        elif ndwi_mean > 0.3:
            recommendations.append("Good moisture levels - no irrigation needed")
        
        # EVI for dense areas
        if evi_mean > 0.5 and ndvi_mean > 0.7:
            recommendations.append("EVI suggests very dense canopy - consider using EVI for monitoring")
        
        return {
            "overall_health": "GOOD" if ndvi_mean > 0.4 and ndwi_mean > 0 else "MODERATE" if ndvi_mean > 0.25 else "POOR",
            "moisture_status": "ADEQUATE" if ndwi_mean > 0 else "STRESSED",
            "vegetation_density": "HIGH" if evi_mean > 0.4 else "MODERATE" if evi_mean > 0.2 else "LOW",
            "recommendations": recommendations
        }


# Singleton instance
_indices_service: Optional[IndicesService] = None


def get_indices_service(use_mock: bool = True) -> IndicesService:
    """Get or create indices service singleton."""
    global _indices_service
    if _indices_service is None:
        _indices_service = IndicesService(use_mock=use_mock)
    return _indices_service
