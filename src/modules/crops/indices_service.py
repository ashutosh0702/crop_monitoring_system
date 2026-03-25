"""
Vegetation index service that creates aligned multi-band stacks per farm scene date.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import shape

from src.config import settings

logger = logging.getLogger(__name__)


class IndicesService:
    """Compute and persist NDVI/SAVI/NDMI/NDRE/EVI stacks from aligned scene bands."""

    INDEX_ORDER = ["NDVI", "SAVI", "NDMI", "NDRE", "EVI"]

    def __init__(self, use_mock: bool = False):
        self.use_mock = use_mock
        self.output_dir = settings.INDEX_STACK_STORAGE_PATH
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.max_workers = max(1, settings.INDEX_CALCULATION_THREADS)

    def calculate_ndvi(self, nir_band: np.ndarray, red_band: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            result = (nir_band.astype(np.float32) - red_band.astype(np.float32)) / (
                nir_band.astype(np.float32) + red_band.astype(np.float32)
            )
        return np.where(np.isfinite(result), result, np.nan).astype(np.float32)

    def calculate_savi(self, nir_band: np.ndarray, red_band: np.ndarray, l: float = 0.5) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            nir = nir_band.astype(np.float32)
            red = red_band.astype(np.float32)
            result = ((nir - red) / (nir + red + l)) * (1 + l)
        return np.where(np.isfinite(result), result, np.nan).astype(np.float32)

    def calculate_ndmi(self, nir_band: np.ndarray, swir1_band: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            nir = nir_band.astype(np.float32)
            swir = swir1_band.astype(np.float32)
            result = (nir - swir) / (nir + swir)
        return np.where(np.isfinite(result), result, np.nan).astype(np.float32)

    def calculate_ndre(self, nir_band: np.ndarray, red_edge_band: np.ndarray) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            nir = nir_band.astype(np.float32)
            red_edge = red_edge_band.astype(np.float32)
            result = (nir - red_edge) / (nir + red_edge)
        return np.where(np.isfinite(result), result, np.nan).astype(np.float32)

    def calculate_evi(
        self,
        nir_band: np.ndarray,
        red_band: np.ndarray,
        blue_band: np.ndarray,
        gain: float = 2.5,
        c1: float = 6.0,
        c2: float = 7.5,
        l: float = 1.0,
    ) -> np.ndarray:
        with np.errstate(divide="ignore", invalid="ignore"):
            nir = nir_band.astype(np.float32)
            red = red_band.astype(np.float32)
            blue = blue_band.astype(np.float32)
            denominator = nir + c1 * red - c2 * blue + l
            result = gain * (nir - red) / denominator
        clipped = np.clip(result, -1, 1)
        return np.where(np.isfinite(clipped), clipped, np.nan).astype(np.float32)

    def get_index_stats(self, index_array: np.ndarray, index_name: str) -> Dict[str, Any]:
        valid_data = index_array[~np.isnan(index_array)]
        if valid_data.size == 0:
            return {
                "index_name": index_name,
                "mean": None,
                "min": None,
                "max": None,
                "std": None,
                "status": "NO_DATA",
            }

        mean_val = float(np.mean(valid_data))
        if index_name == "NDMI":
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
            "status": status,
        }

    def process_all_indices(
        self,
        user_id: str,
        farm_id: str,
        geojson_boundary: dict,
    ) -> Dict[str, Any]:
        """Compute and save the latest available index stack for a farm."""
        scene_inputs = self._load_scene_inputs(geojson_boundary, limit=1)
        if scene_inputs is None:
            return {
                "status": "NO_SATELLITE_DATA",
                "message": "No satellite imagery found for this location",
            }

        scene = scene_inputs[0]
        return self._build_stack_result(user_id, farm_id, scene)

    def build_index_stacks(
        self,
        user_id: str,
        farm_id: str,
        geojson_boundary: dict,
        max_scenes: int = 5,
    ) -> Dict[str, Any]:
        """Build index stacks for the most recent distinct scene dates for a farm."""
        scene_inputs = self._load_scene_inputs(geojson_boundary, limit=max_scenes)
        if scene_inputs is None:
            return {
                "status": "NO_SATELLITE_DATA",
                "message": "No satellite imagery found for this location",
            }

        stacks = [self._build_stack_result(user_id, farm_id, scene_input) for scene_input in scene_inputs]
        return {
            "status": "completed",
            "farm_id": farm_id,
            "stacks": stacks,
        }

    def build_daily_stacks(
        self,
        user_id: str,
        farm_id: str,
        geojson_boundary: dict,
        start_date,
        end_date,
    ) -> Dict[str, Any]:
        """Build a stack for each day in a date range using the best available scene on that day."""
        from datetime import timedelta

        date = start_date
        buffers = []
        while date <= end_date:
            next_day = date + timedelta(days=1)
            scene_inputs = self._load_scene_inputs(
                geojson_boundary,
                limit=1,
                start_date=date,
                end_date=next_day,
            )
            if scene_inputs:
                stack = self._build_stack_result(user_id, farm_id, scene_inputs[0])
                buffers.append(stack)
            date = next_day

        if not buffers:
            return {
                "status": "NO_SATELLITE_DATA",
                "message": "No satellite imagery found in the requested date range",
            }

        return {
            "status": "completed",
            "farm_id": farm_id,
            "stacks": buffers,
        }

    def _load_scene_inputs(
        self,
        geojson_boundary: dict,
        limit: int,
        start_date=None,
        end_date=None,
    ) -> Optional[list[Dict[str, Any]]]:
        polygon_geom = shape(geojson_boundary)

        if self.use_mock:
            scenes = self._build_mock_scene_inputs(polygon_geom.bounds, limit)
        else:
            from src.modules.crops.stac_client import get_stac_client

            client = get_stac_client(use_mock=False)
            raw_scenes = client.search_scenes(
                geometry=geojson_boundary,
                start_date=start_date,
                end_date=end_date,
                max_cloud_cover=30.0,
                limit=max(limit * 2, limit),
            )
            if not raw_scenes:
                return None

            scenes = []
            seen_dates = set()
            for raw_scene in raw_scenes:
                scene_day = raw_scene.datetime.date().isoformat() if raw_scene.datetime else raw_scene.id
                if scene_day in seen_dates:
                    continue
                seen_dates.add(scene_day)

                band_bundle = client.load_scene_bands(
                    raw_scene,
                    geojson_boundary,
                    {
                        "red": raw_scene.red_band_url,
                        "nir": raw_scene.nir_band_url,
                        "blue": raw_scene.blue_band_url,
                        "red_edge": raw_scene.red_edge_band_url,
                        "swir1": raw_scene.swir1_band_url,
                    },
                )
                if band_bundle is None:
                    logger.warning("Skipping scene %s because one or more required bands could not be aligned", raw_scene.id)
                    continue

                scenes.append(
                    {
                        "scene_id": raw_scene.id,
                        "scene_date": raw_scene.datetime or datetime.utcnow(),
                        "cloud_cover": raw_scene.cloud_cover,
                        "source": "sentinel-2",
                        "transform": band_bundle["transform"],
                        "crs": band_bundle["crs"],
                        "bands": band_bundle["bands"],
                    }
                )
                if len(scenes) >= limit:
                    break

        return scenes or None

    def _build_mock_scene_inputs(self, bounds: tuple, limit: int) -> list[Dict[str, Any]]:
        inputs = []
        size = (100, 100)
        transform = from_bounds(*bounds, size[1], size[0])
        now = datetime.utcnow()

        for offset in range(limit):
            inputs.append(
                {
                    "scene_id": f"mock-scene-{offset + 1}",
                    "scene_date": now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=offset * 5),
                    "cloud_cover": float(offset * 3),
                    "source": "mock",
                    "transform": transform,
                    "crs": "EPSG:4326",
                    "bands": {
                        "red": np.random.uniform(0.02, 0.15, size).astype(np.float32),
                        "nir": np.random.uniform(0.35, 0.75, size).astype(np.float32),
                        "blue": np.random.uniform(0.01, 0.08, size).astype(np.float32),
                        "red_edge": np.random.uniform(0.10, 0.28, size).astype(np.float32),
                        "swir1": np.random.uniform(0.08, 0.30, size).astype(np.float32),
                    },
                }
            )

        return inputs

    def _build_stack_result(self, user_id: str, farm_id: str, scene_input: Dict[str, Any]) -> Dict[str, Any]:
        bands = scene_input["bands"]
        index_arrays = self._calculate_indices_parallel(bands)
        index_stats = {
            name: self.get_index_stats(index_arrays[name], name)
            for name in self.INDEX_ORDER
        }

        scene_date = scene_input["scene_date"]
        timestamp = datetime.utcnow()
        filename_stub = f"{user_id}_{farm_id}_{scene_date:%Y%m%dT%H%M%S}_stack"
        stack_path = self.output_dir / f"{filename_stub}.tif"

        self._save_index_stack(
            index_arrays,
            scene_input["transform"],
            scene_input["crs"],
            stack_path,
        )

        return {
            "farm_id": farm_id,
            "scene_date": scene_date.isoformat(),
            "timestamp": timestamp.isoformat(),
            "indices": index_stats,
            "summary": self._generate_summary(index_stats),
            "source": scene_input["source"],
            "stack_tiff_url": str(stack_path),
            "band_order": list(self.INDEX_ORDER),
            "cloud_cover": scene_input["cloud_cover"],
        }

    def _calculate_indices_parallel(self, bands: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        jobs = {
            "NDVI": lambda: self.calculate_ndvi(bands["nir"], bands["red"]),
            "SAVI": lambda: self.calculate_savi(bands["nir"], bands["red"]),
            "NDMI": lambda: self.calculate_ndmi(bands["nir"], bands["swir1"]),
            "NDRE": lambda: self.calculate_ndre(bands["nir"], bands["red_edge"]),
            "EVI": lambda: self.calculate_evi(bands["nir"], bands["red"], bands["blue"]),
        }

        arrays: Dict[str, np.ndarray] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(jobs))) as executor:
            future_map = {
                executor.submit(job): name
                for name, job in jobs.items()
            }
            for future in as_completed(future_map):
                name = future_map[future]
                arrays[name] = future.result()

        return arrays

    def _save_index_stack(
        self,
        index_arrays: Dict[str, np.ndarray],
        transform: Any,
        crs: Any,
        file_path: Path,
    ) -> None:
        first_band = index_arrays[self.INDEX_ORDER[0]]
        with rasterio.open(
            file_path,
            "w",
            driver="GTiff",
            height=first_band.shape[0],
            width=first_band.shape[1],
            count=len(self.INDEX_ORDER),
            dtype="float32",
            crs=crs,
            transform=transform,
            compress="lzw",
        ) as dst:
            for band_number, band_name in enumerate(self.INDEX_ORDER, start=1):
                dst.write(index_arrays[band_name].astype(np.float32), band_number)
                dst.set_band_description(band_number, band_name)

    def _generate_summary(self, index_stats: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        ndvi_mean = index_stats["NDVI"]["mean"]
        ndmi_mean = index_stats["NDMI"]["mean"]
        evi_mean = index_stats["EVI"]["mean"]

        recommendations = []
        if ndvi_mean is not None and ndvi_mean < 0.3:
            recommendations.append("Low vegetation detected - consider crop inspection")
        elif ndvi_mean is not None and ndvi_mean > 0.6:
            recommendations.append("Dense healthy vegetation - optimal conditions")

        if ndmi_mean is not None and ndmi_mean < 0:
            recommendations.append("Water stress detected - irrigation recommended")
        elif ndmi_mean is not None and ndmi_mean > 0.2:
            recommendations.append("Good moisture levels - no irrigation needed")

        if evi_mean is not None and ndvi_mean is not None and evi_mean > 0.5 and ndvi_mean > 0.7:
            recommendations.append("Very dense canopy detected - track with EVI over the season")

        return {
            "overall_health": "GOOD" if ndvi_mean is not None and ndmi_mean is not None and ndvi_mean > 0.4 and ndmi_mean > 0 else "MODERATE" if ndvi_mean is not None and ndvi_mean > 0.25 else "POOR",
            "moisture_status": "ADEQUATE" if ndmi_mean is not None and ndmi_mean > 0 else "STRESSED",
            "vegetation_density": "HIGH" if evi_mean is not None and evi_mean > 0.4 else "MODERATE" if evi_mean is not None and evi_mean > 0.2 else "LOW",
            "recommendations": recommendations,
        }


_indices_services: Dict[bool, IndicesService] = {}


def get_indices_service(use_mock: bool = False) -> IndicesService:
    """Get or create an indices service keyed by mock mode."""
    if use_mock not in _indices_services:
        _indices_services[use_mock] = IndicesService(use_mock=use_mock)
    return _indices_services[use_mock]
