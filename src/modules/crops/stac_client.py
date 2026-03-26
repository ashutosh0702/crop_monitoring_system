"""
STAC API client for Sentinel-2 imagery with aligned multi-band loading.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import ceil
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import rasterio
from PIL import Image
from pystac_client import Client as STACClient
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import reproject, transform_geom
from shapely.geometry import mapping, shape, box

logger = logging.getLogger(__name__)

SCENE_BAND_ATTRS = {
    "red": "red_band_url",
    "nir": "nir_band_url",
    "blue": "blue_band_url",
    "green": "green_band_url",
    "red_edge": "red_edge_band_url",
    "swir1": "swir1_band_url",
}


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


def group_scenes_by_day(scenes: List[SentinelScene]) -> List[List[SentinelScene]]:
    """Group STAC items by acquisition day and order from most recent to oldest."""
    grouped: Dict[str, List[SentinelScene]] = defaultdict(list)
    for scene in scenes:
        key = scene.datetime.date().isoformat() if scene.datetime else scene.id
        grouped[key].append(scene)

    ordered_groups = sorted(
        grouped.values(),
        key=lambda scene_group: max(
            (scene.datetime or datetime.min for scene in scene_group),
            default=datetime.min,
        ),
        reverse=True,
    )

    for scene_group in ordered_groups:
        scene_group.sort(
            key=lambda scene: (
                scene.cloud_cover if scene.cloud_cover is not None else float("inf"),
                scene.id,
            )
        )

    return ordered_groups


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
        """Search for Sentinel-2 scenes intersecting the farm geometry, using Postgres Cache when available."""
        from src.modules.crops.stac_cache_service import STACCacheService
        
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=30)
            
        # 1. Attempt Cache Retrieval
        cached_scenes = STACCacheService.get_cached_scenes(
            geometry, start_date, end_date, max_cloud_cover
        )
        if cached_scenes is not None:
            return cached_scenes[:limit]
            
        # 2. Expand search region to cache neighboring farms
        farm_geom = shape(geometry)
        bounds = farm_geom.bounds
        expanded_bounds = (
            bounds[0] - 0.2,
            bounds[1] - 0.2,
            bounds[2] + 0.2,
            bounds[3] + 0.2
        )
        search_geom = mapping(box(*expanded_bounds))

        date_range = f"{start_date:%Y-%m-%d}/{end_date:%Y-%m-%d}"
        logger.info("Searching STAC scenes for %s with cloud cover < %.1f", date_range, max_cloud_cover)

        try:
            search = self.client.search(
                collections=[self.SENTINEL2_COLLECTION],
                intersects=search_geom,
                datetime=date_range,
                query={"eo:cloud_cover": {"lt": max_cloud_cover}},
                sortby=[
                    {"field": "properties.datetime", "direction": "desc"},
                    {"field": "properties.eo:cloud_cover", "direction": "asc"},
                ],
                max_items=limit * 5,  # Fetch extra for cache
            )

            scenes = []
            for item in search.items():
                scene = self._parse_item(item)
                if scene is not None:
                    scenes.append(scene)

            logger.info("Found %d matching scenes from API", len(scenes))
            
            if scenes:
                STACCacheService.cache_search_results(
                    search_geom=search_geom,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                    scenes=scenes,
                )
                
            # Filter to original geometry
            filtered_scenes = [
                s for s in scenes
                if s.bbox and farm_geom.intersects(box(*s.bbox))
            ]

            return filtered_scenes[:limit]
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
        return self.stream_band_collection_data(
            [band_url],
            geometry,
            target_shape=target_shape,
            target_transform=target_transform,
            target_crs=target_crs,
            resampling=resampling,
        )

    def _masked_to_float32(self, masked_band: np.ma.MaskedArray, nodata: Any) -> np.ndarray:
        band_array = np.asarray(masked_band.data, dtype=np.float32)
        band_mask = np.ma.getmaskarray(masked_band)
        if band_mask.any():
            band_array[band_mask] = np.nan

        if nodata is not None:
            band_array[band_array == float(nodata)] = np.nan

        return band_array

    def _build_target_grid(
        self,
        geometry: dict,
        target_crs: Any,
        xres: float,
        yres: float,
    ) -> Tuple[Tuple[int, int], Any]:
        geom_target = shape(transform_geom("EPSG:4326", target_crs, geometry))
        minx, miny, maxx, maxy = geom_target.bounds
        width = max(1, int(ceil((maxx - minx) / xres)))
        height = max(1, int(ceil((maxy - miny) / yres)))
        transform = from_origin(minx, maxy, xres, yres)
        return (height, width), transform

    def stream_band_collection_data(
        self,
        band_urls: List[str],
        geometry: dict,
        target_shape: Optional[Tuple[int, int]] = None,
        target_transform: Any = None,
        target_crs: Any = None,
        resampling: Resampling = Resampling.bilinear,
    ) -> Optional[MaskedBand]:
        """Stream one or more band rasters, mosaic them, and clip the result to the farm geometry."""
        if not band_urls:
            return None

        datasets = []
        try:
            with rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
            ):
                datasets = [rasterio.open(url) for url in band_urls]
                if not datasets:
                    return None

                resolved_target_crs = target_crs or datasets[0].crs
                if (
                    target_shape is None
                    or target_transform is None
                    or resolved_target_crs is None
                ):
                    xres, yres = datasets[0].res
                    resolved_target_shape, resolved_target_transform = self._build_target_grid(
                        geometry,
                        datasets[0].crs,
                        abs(float(xres)),
                        abs(float(yres)),
                    )
                    resolved_target_crs = datasets[0].crs
                else:
                    resolved_target_shape = target_shape
                    resolved_target_transform = target_transform

                mosaic = np.full(resolved_target_shape, np.nan, dtype=np.float32)
                any_overlap = False

                for src in datasets:
                    try:
                        geom_transformed = transform_geom("EPSG:4326", src.crs, geometry)
                        geom = shape(geom_transformed)
                        logger.debug(
                            "Transformed geometry from EPSG:4326 to %s for band masking",
                            src.crs,
                        )

                        out_image, out_transform = mask(
                            src,
                            [mapping(geom)],
                            crop=True,
                            filled=False,
                        )
                    except ValueError:
                        logger.debug("Band %s does not overlap the farm geometry", src.name)
                        continue

                    any_overlap = True
                    band_array = self._masked_to_float32(out_image[0], src.nodata)
                    aligned = np.full(resolved_target_shape, np.nan, dtype=np.float32)
                    reproject(
                        source=band_array,
                        destination=aligned,
                        src_transform=out_transform,
                        src_crs=src.crs,
                        src_nodata=np.nan,
                        dst_transform=resolved_target_transform,
                        dst_crs=resolved_target_crs,
                        dst_nodata=np.nan,
                        resampling=resampling,
                    )

                    fill_mask = np.isnan(mosaic) & np.isfinite(aligned)
                    if fill_mask.any():
                        mosaic[fill_mask] = aligned[fill_mask]

                if not any_overlap:
                    return None

                geom_target = transform_geom("EPSG:4326", resolved_target_crs, geometry)
                inside_geometry = geometry_mask(
                    [geom_target],
                    out_shape=resolved_target_shape,
                    transform=resolved_target_transform,
                    invert=True,
                )
                mosaic[~inside_geometry] = np.nan

                return MaskedBand(
                    array=mosaic,
                    transform=resolved_target_transform,
                    crs=resolved_target_crs,
                )
        except Exception as exc:
            logger.error("Failed to stream band collection %s: %s", band_urls, exc)
            return None
        finally:
            for dataset in datasets:
                dataset.close()

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
        """Backward-compatible single-scene band loader."""
        band_names = [name for name, url in requested_bands.items() if url]
        return self.load_scene_group_bands([scene], geometry, band_names)

    def load_scene_group_bands(
        self,
        scenes: Iterable[SentinelScene],
        geometry: dict,
        band_names: Iterable[str],
    ) -> Optional[Dict[str, Any]]:
        """Load and align requested bands for one acquisition day, mosaicking all overlapping tiles."""
        scene_list = [scene for scene in scenes if scene is not None]
        requested_urls: Dict[str, List[str]] = {}

        for band_name in band_names:
            band_attr = SCENE_BAND_ATTRS.get(band_name)
            if band_attr is None:
                logger.warning("Unsupported band requested for scene mosaic: %s", band_name)
                continue

            urls = [
                getattr(scene, band_attr)
                for scene in scene_list
                if getattr(scene, band_attr, None)
            ]
            if urls:
                requested_urls[band_name] = urls

        if not requested_urls:
            return None

        reference_name = "red" if "red" in requested_urls else next(iter(requested_urls))
        reference_band = self.stream_band_collection_data(requested_urls[reference_name], geometry)
        if reference_band is None:
            return None

        bands = {reference_name: reference_band.array}
        for name, urls in requested_urls.items():
            if name == reference_name:
                continue

            band = self.stream_band_collection_data(
                urls,
                geometry,
                target_shape=reference_band.array.shape,
                target_transform=reference_band.transform,
                target_crs=reference_band.crs,
            )
            if band is None:
                scene_ids = ",".join(scene.id for scene in scene_list)
                logger.error("Missing aligned band '%s' for scene group %s", name, scene_ids)
                return None
            bands[name] = band.array

        return {
            "bands": bands,
            "transform": reference_band.transform,
            "crs": reference_band.crs,
        }



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
        band_names = [name for name, url in requested_bands.items() if url]
        return self.load_scene_group_bands([scene], geometry, band_names)

    def load_scene_group_bands(
        self,
        scenes: Iterable[SentinelScene],
        geometry: dict,
        band_names: Iterable[str],
    ) -> Optional[Dict[str, Any]]:
        scene_list = [scene for scene in scenes if scene is not None]
        band_urls: Dict[str, List[str]] = {}

        for band_name in band_names:
            band_attr = SCENE_BAND_ATTRS.get(band_name)
            if band_attr is None:
                continue

            urls = [
                getattr(scene, band_attr)
                for scene in scene_list
                if getattr(scene, band_attr, None)
            ]
            if urls:
                band_urls[band_name] = urls

        if not band_urls:
            return None

        geom = shape(geometry)
        bounds = geom.bounds
        target_shape = (100, 100)
        transform = from_bounds(*bounds, target_shape[1], target_shape[0])
        bands = {
            name: self._generate_band(urls[0], target_shape)
            for name, urls in band_urls.items()
        }
        return {
            "bands": bands,
            "transform": transform,
            "crs": "EPSG:4326",
        }



def get_stac_client(use_mock: bool = False):
    """Return either the real STAC client or the mock implementation."""
    if use_mock:
        return MockSTACClient()
    return STACImageryClient()
