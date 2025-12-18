import os
import numpy as np
import rasterio
from rasterio.mask import mask
from shapely.geometry import shape
import uuid
from datetime import datetime
from pathlib import Path
from src.config import settings

class NDVILogic:
    def __init__(self):
        
        self.storage_path = settings.TIFF_STORAGE_PATH
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
    def calculate_ndvi_stats(self, ndvi_array):
        """Standard Linear Classification Logic"""
        # Filter out NoData (usually -1 or 0 in NDVI)
        valid_ndvi = ndvi_array[~np.isnan(ndvi_array)]
        if valid_ndvi.size == 0:
            return 0, "DATA_MISSING"

        mean_val = float(np.mean(valid_ndvi))
        
        if mean_val >= 0.50:
            status = "HEALTHY"
        elif mean_val >= 0.25:
            status = "MODERATE"
        else:
            status = "CRITICAL"
            
        return mean_val, status

    async def process_field_ndvi(self, user_id: str, farm_id: str,geojson_boundary: dict):
        """
        1. MOCK: Fetching Red/NIR bands from Satellite API
        2. Process: (NIR - Red) / (NIR + Red)
        3. Save: Export GeoTiff
        """

        
        # Convert GeoJSON to Shapely for masking
        polygon_geom = shape(geojson_boundary)
        
        # --- SATELLITE FETCH MOCK ---
        # In a real scenario, you'd fetch the latest Sentinel-2 scene from 
        # Agromonitoring or AWS S3 (Sentinel-Public-Dataset)
        # For MVP, we generate dummy data with the same bounds as the polygon
        bounds = polygon_geom.bounds # (minx, miny, maxx, maxy)
        
        # Simulate a 100x100 resolution raster
        red_band = np.random.uniform(0, 0.2, (100, 100))
        nir_band = np.random.uniform(0.3, 0.8, (100, 100))
        
        # NDVI Calculation
        # Avoid division by zero
        denom = (nir_band + red_band)
        ndvi = np.where(denom == 0, 0, (nir_band - red_band) / denom)

        # Generate unique filename
        # NEW STRATEGIC NAMING: USERID_FARMID_TIMESTAMP
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{user_id}_{farm_id}_{timestamp}.tif"
        file_path = self.storage_path / filename
        print(file_path)
        # --- SAVE AS GEOTIFF ---
        # We use a dummy transform for MVP. In Production, we use the 
        # transform from the source Sentinel image.
        from rasterio.transform import from_bounds
        transform = from_bounds(*bounds, 100, 100)

        print(filename)
        print(os.getcwd())
        print(file_path)
        
        with rasterio.open(
            file_path, 'w', driver='GTiff',
            height=ndvi.shape[0], width=ndvi.shape[1],
            count=1, dtype=ndvi.dtype,
            crs='EPSG:4326', transform=transform
        ) as dst:
            dst.write(ndvi, 1)

        # Calculate Stats
        mean_ndvi, status = self.calculate_ndvi_stats(ndvi)

        
        
        return {
            "tiff_url": str(file_path),
            "stats": {
                "mean_ndvi": round(mean_ndvi, 3),
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
        }