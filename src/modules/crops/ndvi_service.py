"""
NDVI analysis service built on aligned STAC band loading.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_bounds
from shapely.geometry import shape

from src.config import settings
from src.core.utils import file_to_data_url
from src.modules.crops.stac_client import group_scenes_by_day
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)


class NDVILogic:
    """Compute NDVI for a farm and persist GeoTIFF/PNG artifacts."""

    def __init__(self, use_mock: bool = True):
        self.use_mock = use_mock
        self.tiff_storage = settings.TIFF_STORAGE_PATH
        self.png_storage = settings.PNG_STORAGE_PATH
        self.tiff_storage.mkdir(parents=True, exist_ok=True)
        self.png_storage.mkdir(parents=True, exist_ok=True)
        self._stac_client = None

    @property
    def stac_client(self):
        if self._stac_client is None:
            from src.modules.crops.stac_client import get_stac_client

            self._stac_client = get_stac_client(use_mock=self.use_mock)
        return self._stac_client

    def calculate_ndvi_stats(self, ndvi_array: np.ndarray) -> Dict[str, Any]:
        valid_ndvi = ndvi_array[~np.isnan(ndvi_array)]
        if valid_ndvi.size == 0:
            return {
                "mean_ndvi": 0.0,
                "min_ndvi": None,
                "max_ndvi": None,
                "std_ndvi": None,
                "status": "DATA_MISSING",
            }

        mean_val = float(np.mean(valid_ndvi))
        if mean_val >= 0.50:
            status = "HEALTHY"
        elif mean_val >= 0.25:
            status = "MODERATE"
        else:
            status = "CRITICAL"

        return {
            "mean_ndvi": mean_val,
            "min_ndvi": float(np.min(valid_ndvi)),
            "max_ndvi": float(np.max(valid_ndvi)),
            "std_ndvi": float(np.std(valid_ndvi)),
            "status": status,
        }

    def process_field_ndvi(
        self,
        user_id: str,
        farm_id: str,
        geojson_boundary: dict,
    ) -> Dict[str, Any]:
        """Compute NDVI for the best available scene and save raster artifacts."""
        polygon_geom = shape(geojson_boundary)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_filename = f"{user_id}_{farm_id}_{timestamp}"
        tiff_path = self.tiff_storage / f"{base_filename}.tif"
        png_path = self.png_storage / f"{base_filename}.png"

        band_bundle = None
        satellite_source = "mock" if self.use_mock else "sentinel-2"
        scene_date = None
        cloud_cover = None

        if self.use_mock:
            logger.info("Using mock NDVI data for farm %s", farm_id)
            band_bundle = self._build_mock_band_bundle(polygon_geom.bounds)
        else:
            logger.info("Fetching Sentinel-2 NDVI data for farm %s", farm_id)
            try:
                scenes = self.stac_client.search_scenes(
                    geometry=geojson_boundary,
                    max_cloud_cover=30.0,
                    limit=16,
                )
                scene_groups = group_scenes_by_day(scenes)
                if scene_groups:
                    scene_group = scene_groups[0]
                    band_bundle = self.stac_client.load_scene_group_bands(
                        scene_group,
                        geojson_boundary,
                        ["red", "nir"],
                    )
                    if band_bundle is not None:
                        satellite_source = "sentinel-2"
                        scene_datetimes = [
                            item.datetime
                            for item in scene_group
                            if item.datetime is not None
                        ]
                        scene_date = max(scene_datetimes) if scene_datetimes else None
                        cloud_values = [
                            item.cloud_cover
                            for item in scene_group
                            if item.cloud_cover is not None
                        ]
                        cloud_cover = (
                            float(np.mean(cloud_values))
                            if cloud_values
                            else None
                        )
                if band_bundle is None:
                    logger.warning("Falling back to mock NDVI data for farm %s", farm_id)
                    band_bundle = self._build_mock_band_bundle(polygon_geom.bounds)
                    satellite_source = "mock"
                    scene_date = None
                    cloud_cover = None
            except Exception as exc:
                logger.error("NDVI STAC fetch failed for farm %s: %s", farm_id, exc)
                band_bundle = self._build_mock_band_bundle(polygon_geom.bounds)
                satellite_source = "mock"
                scene_date = None
                cloud_cover = None

        red_band = band_bundle["bands"]["red"]
        nir_band = band_bundle["bands"]["nir"]

        ndvi = self._calculate_ndvi(nir_band, red_band)
        self._save_geotiff(
            ndvi,
            band_bundle["transform"],
            band_bundle["crs"],
            tiff_path,
        )
        self._save_ndvi_png(ndvi, png_path)

        stats = self.calculate_ndvi_stats(ndvi)
        stats["timestamp"] = datetime.utcnow().isoformat()

        return {
            "tiff_url": str(tiff_path),
            "png_url": str(png_path),
            "png_data_url": file_to_data_url(str(png_path), "image/png"),
            "stats": stats,
            "metadata": {
                "satellite_source": satellite_source,
                "scene_date": scene_date.isoformat() if scene_date else None,
                "cloud_cover": cloud_cover,
            },
        }

    def _build_mock_band_bundle(self, bounds: tuple, size: tuple[int, int] = (100, 100)) -> Dict[str, Any]:
        transform = from_bounds(*bounds, size[1], size[0])
        return {
            "bands": {
                "red": np.random.uniform(0.02, 0.15, size).astype(np.float32),
                "nir": np.random.uniform(0.35, 0.75, size).astype(np.float32),
                "green": np.random.uniform(0.05, 0.20, size).astype(np.float32),
            },
            "transform": transform,
            "crs": "EPSG:4326",
        }

    def _calculate_ndvi(self, nir: np.ndarray, red: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            denom = nir.astype(np.float32) + red.astype(np.float32)
            ndvi = np.where(denom == 0, np.nan, (nir - red) / denom)
        return np.where(np.isfinite(ndvi), ndvi, np.nan).astype(np.float32)

    def _save_geotiff(
        self,
        ndvi: np.ndarray,
        transform: Any,
        crs: Any,
        file_path: Path,
    ) -> None:
        with rasterio.open(
            file_path,
            "w",
            driver="GTiff",
            height=ndvi.shape[0],
            width=ndvi.shape[1],
            count=1,
            dtype="float32",
            crs=crs,
            transform=transform,
            compress="lzw",
        ) as dst:
            dst.write(ndvi.astype(np.float32), 1)
            dst.set_band_description(1, "NDVI")

    # def _save_ndvi_png(self, ndvi: np.ndarray, file_path: Path) -> None:
    #     valid = np.nan_to_num(ndvi, nan=-1.0)
    #     normalized = np.clip((valid + 1) / 2, 0, 1)
    #     rgba = np.zeros((ndvi.shape[0], ndvi.shape[1], 4), dtype=np.uint8)
    #     rgba[..., 0] = ((1 - normalized) * 165).astype(np.uint8)
    #     rgba[..., 1] = (normalized * 200).astype(np.uint8)
    #     rgba[..., 2] = ((normalized > 0.5) * 40).astype(np.uint8)
    #     rgba[..., 3] = np.where(np.isnan(ndvi), 0, 255).astype(np.uint8)
    #     Image.fromarray(rgba).save(file_path, "PNG")

    def _save_ndvi_png(self, ndvi: np.ndarray, file_path: Path) -> None:
    # 1. Identify valid vs invalid pixels (NaNs or Infs)
    # This creates a boolean mask where True = valid data
        is_valid = np.isfinite(ndvi)
        
        # 2. Get the Colormap
        cmap = plt.get_cmap('RdYlGn')
        
        # 3. Normalize the data specifically for the colormap
        # We clip to [-1, 1] to ensure we don't go out of bounds
        ndvi_clipped = np.clip(ndvi, -1.0, 1.0)
        norm_data = (ndvi_clipped + 1) / 2.0
        
        # 4. Apply Colormap 
        # This creates an RGB array (ignoring alpha for a moment)
        rgb_floats = cmap(norm_data)[:, :, :3]  # Take only R, G, and B
        
        # 5. Build the RGBA uint8 array
        # Initialize as all zeros (fully transparent)
        h, w = ndvi.shape
        rgba_uint8 = np.zeros((h, w, 4), dtype=np.uint8)
        
        # Fill RGB for all pixels
        rgba_uint8[..., :3] = (rgb_floats * 255).astype(np.uint8)
        
        # 6. Set Sharp Alpha
        # Valid pixels = 255 (100% opaque), Invalid pixels = 0 (100% transparent)
        rgba_uint8[..., 3] = np.where(is_valid, 255, 0).astype(np.uint8)
        
        # 7. Save without any smoothing/compression artifacts
        Image.fromarray(rgba_uint8).save(file_path, "PNG", optimize=True)