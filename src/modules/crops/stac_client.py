"""
STAC API client for Sentinel-2 imagery with aligned multi-band loading.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import rasterio
from PIL import Image
from pystac_client import Client as STACClient
from rasterio.enums import Resampling
from rasterio.mask import mask
from rasterio.transform import from_bounds
from rasterio.warp import reproject
from shapely.geometry import mapping, shape

logger = logging.getLogger(__name__)


@dataclass
class SentinelScene:
    """Represents a Sentinel-2 scene and the band assets needed by the app."""

    id: str
    datetime: datetime
    cloud_cover: float
    red_band_url: str
    nir_band_url: str
    blue_band_url: Optional[str] = None
    green_band_url: Optional[str] = None
    red_edge_band_url: Optional[str] = None
    swir1_band_url: Optional[str] = None
    bbox: Optional[List[float]] = None


@dataclass
class MaskedBand:
    """A masked band aligned to a target grid."""

    array: np.ndarray
    transform: Any
    crs: Any


class STACImageryClient:
    """Client for fetching Sentinel-2 imagery via Element84 Earth Search."""

    EARTH_SEARCH_URL = "https://earth-search.aws.element84.com/v1"
    SENTINEL2_COLLECTION = "sentinel-2-l2a"

    def __init__(self, stac_url: Optional[str] = None):
        self.stac_url = stac_url or self.EARTH_SEARCH_URL
        self.client = STACClient.open(self.stac_url)

    def search_scenes(
        self,
        geometry: dict,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_cloud_cover: float = 30.0,
        limit: int = 5,
    ) -> List[SentinelScene]:
        """Search for Sentinel-2 scenes intersecting the farm geometry."""
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        date_range = f"{start_date:%Y-%m-%d}/{end_date:%Y-%m-%d}"
        logger.info("Searching STAC scenes for %s with cloud cover < %.1f", date_range, max_cloud_cover)

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
                if scene is not None:
                    scenes.append(scene)

            logger.info("Found %d matching scenes", len(scenes))
            return scenes
        except Exception as exc:
            logger.error("STAC search failed: %s", exc)
            return []

    def _parse_item(self, item) -> Optional[SentinelScene]:
        """Parse a STAC item into the set of assets we need."""
        try:
            assets = item.assets
            red_asset = assets.get("red") or assets.get("B04")
            nir_asset = assets.get("nir") or assets.get("B08")
            blue_asset = assets.get("blue") or assets.get("B02")
            green_asset = assets.get("green") or assets.get("B03")
            red_edge_asset = assets.get("rededge1") or assets.get("B05")
            swir1_asset = assets.get("swir16") or assets.get("B11")

            if not red_asset or not nir_asset:
                logger.warning("Skipping item %s because core bands are missing", item.id)
                return None

            return SentinelScene(
                id=item.id,
                datetime=item.datetime,
                cloud_cover=item.properties.get("eo:cloud_cover", 0),
                red_band_url=red_asset.href,
                nir_band_url=nir_asset.href,
                blue_band_url=blue_asset.href if blue_asset else None,
                green_band_url=green_asset.href if green_asset else None,
                red_edge_band_url=red_edge_asset.href if red_edge_asset else None,
                swir1_band_url=swir1_asset.href if swir1_asset else None,
                bbox=item.bbox,
            )
        except Exception as exc:
            logger.error("Failed to parse STAC item: %s", exc)
            return None

    def stream_and_mask_band_data(
        self,
        band_url: str,
        geometry: dict,
        target_shape: Optional[Tuple[int, int]] = None,
        target_transform: Any = None,
        target_crs: Any = None,
        resampling: Resampling = Resampling.bilinear,
    ) -> Optional[MaskedBand]:
        """Stream a COG band, mask it to geometry, and optionally align it to a target grid."""
        try:
            with rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
            ):
                with rasterio.open(band_url) as src:
                    geom = shape(geometry)
                    out_image, out_transform = mask(
                        src,
                        [mapping(geom)],
                        crop=True,
                        filled=True,
                        nodata=np.nan,
                    )

                    band_array = out_image[0].astype(np.float32, copy=False)
                    band_crs = src.crs

                    if target_shape and target_transform is not None and target_crs is not None:
                        if band_array.shape != target_shape or out_transform != target_transform or band_crs != target_crs:
                            aligned = np.full(target_shape, np.nan, dtype=np.float32)
                            reproject(
                                source=band_array,
                                destination=aligned,
                                src_transform=out_transform,
                                src_crs=band_crs,
                                src_nodata=np.nan,
                                dst_transform=target_transform,
                                dst_crs=target_crs,
                                dst_nodata=np.nan,
                                resampling=resampling,
                            )
                            return MaskedBand(array=aligned, transform=target_transform, crs=target_crs)

                    return MaskedBand(array=band_array, transform=out_transform, crs=band_crs)
        except Exception as exc:
            logger.error("Failed to stream band %s: %s", band_url, exc)
            return None

    def stream_and_mask_band(
        self,
        band_url: str,
        geometry: dict,
        resolution: Tuple[int, int] = (100, 100),
    ) -> Optional[np.ndarray]:
        """Backward-compatible band loader returning just the masked array."""
        band = self.stream_and_mask_band_data(band_url, geometry)
        return None if band is None else band.array

    def load_scene_bands(
        self,
        scene: SentinelScene,
        geometry: dict,
        requested_bands: Dict[str, Optional[str]],
    ) -> Optional[Dict[str, Any]]:
        """Load and align all requested bands for a scene onto the red band grid."""
        band_urls = {name: url for name, url in requested_bands.items() if url}
        if not band_urls:
            return None

        reference_name = "red" if "red" in band_urls else next(iter(band_urls))
        reference_band = self.stream_and_mask_band_data(band_urls[reference_name], geometry)
        if reference_band is None:
            return None

        bands = {reference_name: reference_band.array}
        for name, url in band_urls.items():
            if name == reference_name:
                continue

            band = self.stream_and_mask_band_data(
                url,
                geometry,
                target_shape=reference_band.array.shape,
                target_transform=reference_band.transform,
                target_crs=reference_band.crs,
            )
            if band is None:
                logger.error("Missing aligned band '%s' for scene %s", name, scene.id)
                return None
            bands[name] = band.array

        return {
            "bands": bands,
            "transform": reference_band.transform,
            "crs": reference_band.crs,
        }

    def create_false_color_composite(
        self,
        nir_array: np.ndarray,
        red_array: np.ndarray,
        green_array: np.ndarray,
        output_path: str,
    ) -> bool:
        """Create a false-color PNG using aligned NIR, red, and green bands."""

        def normalize(arr: np.ndarray) -> np.ndarray:
            arr = np.nan_to_num(arr, nan=0.0)
            arr_min, arr_max = np.percentile(arr, [2, 98])
            if arr_max <= arr_min:
                return np.zeros_like(arr, dtype=np.uint8)
            scaled = np.clip((arr - arr_min) / (arr_max - arr_min) * 255, 0, 255)
            return scaled.astype(np.uint8)

        try:
            rgb = np.dstack([
                normalize(nir_array),
                normalize(red_array),
                normalize(green_array),
            ])
            Image.fromarray(rgb).save(output_path, "PNG")
            logger.info("Saved false color composite to %s", output_path)
            return True
        except Exception as exc:
            logger.error("Failed to create false color composite: %s", exc)
            return False


class MockSTACClient:
    """Mock STAC client returning synthetic but shape-aligned data."""

    def search_scenes(self, geometry: dict, **kwargs) -> List[SentinelScene]:
        now = datetime.utcnow()
        return [
            SentinelScene(
                id=f"mock-scene-{offset}",
                datetime=now - timedelta(days=offset * 5),
                cloud_cover=float(offset * 3),
                red_band_url="mock://sentinel-2/B04.tif",
                nir_band_url="mock://sentinel-2/B08.tif",
                blue_band_url="mock://sentinel-2/B02.tif",
                green_band_url="mock://sentinel-2/B03.tif",
                red_edge_band_url="mock://sentinel-2/B05.tif",
                swir1_band_url="mock://sentinel-2/B11.tif",
            )
            for offset in range(1, 6)
        ]

    def _generate_band(self, band_url: str, shape_hint: Tuple[int, int]) -> np.ndarray:
        if "B02" in band_url or "blue" in band_url.lower():
            return np.random.uniform(0.01, 0.08, shape_hint).astype(np.float32)
        if "B03" in band_url or "green" in band_url.lower():
            return np.random.uniform(0.03, 0.12, shape_hint).astype(np.float32)
        if "B04" in band_url or "red" in band_url.lower():
            return np.random.uniform(0.02, 0.10, shape_hint).astype(np.float32)
        if "B05" in band_url or "rededge" in band_url.lower():
            return np.random.uniform(0.12, 0.30, shape_hint).astype(np.float32)
        if "B11" in band_url or "swir" in band_url.lower():
            return np.random.uniform(0.08, 0.28, shape_hint).astype(np.float32)
        return np.random.uniform(0.35, 0.75, shape_hint).astype(np.float32)

    def stream_and_mask_band_data(
        self,
        band_url: str,
        geometry: dict,
        target_shape: Optional[Tuple[int, int]] = None,
        target_transform: Any = None,
        target_crs: Any = None,
        resampling: Resampling = Resampling.bilinear,
    ) -> Optional[MaskedBand]:
        shape_hint = target_shape or (100, 100)
        geom = shape(geometry)
        bounds = geom.bounds
        transform = target_transform or from_bounds(*bounds, shape_hint[1], shape_hint[0])
        crs = target_crs or "EPSG:4326"
        return MaskedBand(
            array=self._generate_band(band_url, shape_hint),
            transform=transform,
            crs=crs,
        )

    def stream_and_mask_band(
        self,
        band_url: str,
        geometry: dict,
        resolution: Tuple[int, int] = (100, 100),
    ) -> np.ndarray:
        return self._generate_band(band_url, resolution)

    def load_scene_bands(
        self,
        scene: SentinelScene,
        geometry: dict,
        requested_bands: Dict[str, Optional[str]],
    ) -> Optional[Dict[str, Any]]:
        band_urls = {name: url for name, url in requested_bands.items() if url}
        if not band_urls:
            return None

        geom = shape(geometry)
        bounds = geom.bounds
        target_shape = (100, 100)
        transform = from_bounds(*bounds, target_shape[1], target_shape[0])
        bands = {
            name: self._generate_band(url, target_shape)
            for name, url in band_urls.items()
        }
        return {
            "bands": bands,
            "transform": transform,
            "crs": "EPSG:4326",
        }

    def create_false_color_composite(
        self,
        nir_array: np.ndarray,
        red_array: np.ndarray,
        green_array: np.ndarray,
        output_path: str,
    ) -> bool:
        try:
            rgb = np.dstack([
                np.clip(nir_array * 255, 0, 255).astype(np.uint8),
                np.clip(red_array * 255, 0, 255).astype(np.uint8),
                np.clip(green_array * 255, 0, 255).astype(np.uint8),
            ])
            Image.fromarray(rgb).save(output_path, "PNG")
            return True
        except Exception as exc:
            logger.error("Failed to create mock false color composite: %s", exc)
            return False


def get_stac_client(use_mock: bool = False):
    """Return either the real STAC client or the mock implementation."""
    if use_mock:
        return MockSTACClient()
    return STACImageryClient()
