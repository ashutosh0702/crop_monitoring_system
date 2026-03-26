from datetime import datetime, timedelta

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box, mapping

from src.modules.crops.stac_client import (
    STACImageryClient,
    SentinelScene,
    group_scenes_by_day,
)


def _make_client() -> STACImageryClient:
    return object.__new__(STACImageryClient)


def _write_uint16_band(path, data: np.ndarray) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(0, 4, 1, 1),
        nodata=0,
    ) as dst:
        dst.write(data, 1)


def test_stream_and_mask_band_data_converts_uint16_masks_to_float32(tmp_path) -> None:
    raster_path = tmp_path / "B04.tif"
    data = np.arange(1, 17, dtype=np.uint16).reshape(4, 4)
    _write_uint16_band(raster_path, data)

    geometry = mapping(Polygon([(0.5, 3.5), (3.5, 3.5), (2.0, 0.5)]))

    result = _make_client().stream_and_mask_band_data(str(raster_path), geometry)

    assert result is not None
    assert result.array.dtype == np.float32
    assert np.isfinite(result.array).any()
    assert np.isnan(result.array).any()


def test_stream_and_mask_band_data_reprojects_float_output(tmp_path) -> None:
    raster_path = tmp_path / "B08.tif"
    data = np.full((4, 4), 100, dtype=np.uint16)
    _write_uint16_band(raster_path, data)

    result = _make_client().stream_and_mask_band_data(
        str(raster_path),
        mapping(box(0, 0, 4, 4)),
        target_shape=(2, 2),
        target_transform=from_origin(0, 4, 2, 2),
        target_crs="EPSG:4326",
    )

    assert result is not None
    assert result.array.shape == (2, 2)
    assert result.array.dtype == np.float32
    assert np.all(np.isfinite(result.array))


def test_load_scene_group_bands_mosaics_adjacent_tiles(tmp_path) -> None:
    left_path = tmp_path / "left_B04.tif"
    right_path = tmp_path / "right_B04.tif"

    with rasterio.open(
        left_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(0, 2, 1, 1),
        nodata=0,
    ) as dst:
        dst.write(np.full((2, 2), 10, dtype=np.uint16), 1)

    with rasterio.open(
        right_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(2, 2, 1, 1),
        nodata=0,
    ) as dst:
        dst.write(np.full((2, 2), 20, dtype=np.uint16), 1)

    scene_time = datetime(2026, 2, 25, 5, 0, 0)
    scenes = [
        SentinelScene(
            id="tile-left",
            datetime=scene_time,
            cloud_cover=4.0,
            red_band_url=str(left_path),
            nir_band_url=str(left_path),
        ),
        SentinelScene(
            id="tile-right",
            datetime=scene_time,
            cloud_cover=6.0,
            red_band_url=str(right_path),
            nir_band_url=str(right_path),
        ),
    ]

    result = _make_client().load_scene_group_bands(
        scenes,
        mapping(box(0, 0, 4, 2)),
        ["red"],
    )

    assert result is not None
    assert result["bands"]["red"].shape == (2, 4)
    assert np.allclose(result["bands"]["red"][:, :2], 10.0)
    assert np.allclose(result["bands"]["red"][:, 2:], 20.0)


def test_group_scenes_by_day_orders_newest_first() -> None:
    newer = datetime(2026, 2, 26, 10, 0, 0)
    older = newer - timedelta(days=1)
    scenes = [
        SentinelScene(
            id="older",
            datetime=older,
            cloud_cover=2.0,
            red_band_url="older-red",
            nir_band_url="older-nir",
        ),
        SentinelScene(
            id="newer-b",
            datetime=newer,
            cloud_cover=8.0,
            red_band_url="newer-b-red",
            nir_band_url="newer-b-nir",
        ),
        SentinelScene(
            id="newer-a",
            datetime=newer,
            cloud_cover=3.0,
            red_band_url="newer-a-red",
            nir_band_url="newer-a-nir",
        ),
    ]

    grouped = group_scenes_by_day(scenes)

    assert [scene.id for scene in grouped[0]] == ["newer-a", "newer-b"]
    assert [scene.id for scene in grouped[1]] == ["older"]
