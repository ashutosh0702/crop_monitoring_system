"""
Service for proxying STAC API calls through a local Postgres PostGIS cache.
"""

import logging
from datetime import datetime
from typing import List, Optional

from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape
from sqlalchemy import func

from src.database import get_db_session
from src.models import STACSceneCache, STACSearchRegion
from src.modules.crops.stac_client import SentinelScene

logger = logging.getLogger(__name__)


class STACCacheService:
    @staticmethod
    def get_cached_scenes(
        geometry: dict,
        start_date: datetime,
        end_date: datetime,
        max_cloud_cover: float,
    ) -> Optional[List[SentinelScene]]:
        """
        Check if the requested geometry + time period has already been searched.
        If yes, return the scenes from the local cache. If no, return None.
        """
        shapely_geom = shape(geometry)
        postgis_geom = from_shape(shapely_geom, srid=4326)

        try:
            with get_db_session() as db:
                # 1. Has this exact geometry (or a region encompassing it) been searched?
                cached_region = (
                    db.query(STACSearchRegion)
                    .filter(
                        func.ST_Within(postgis_geom, STACSearchRegion.geom),
                        STACSearchRegion.start_date <= start_date,
                        STACSearchRegion.end_date >= end_date,
                        STACSearchRegion.max_cloud_cover >= max_cloud_cover,
                    )
                    .first()
                )

                if not cached_region:
                    return None  # Cache miss

                # 2. It's a cache hit. Retrieve all scenes overlapping this specific geometry
                cached_scenes = (
                    db.query(STACSceneCache)
                    .filter(
                        func.ST_Intersects(STACSceneCache.geom, postgis_geom),
                        STACSceneCache.datetime >= start_date,
                        STACSceneCache.datetime <= end_date,
                        STACSceneCache.cloud_cover <= max_cloud_cover,
                    )
                    .order_by(STACSceneCache.datetime.desc(), STACSceneCache.cloud_cover.asc())
                    .all()
                )

                logger.info("STAC Cache Hit! Found %d scenes in local DB DB bypassing API.", len(cached_scenes))

                scenes = []
                for item in cached_scenes:
                    assets = item.assets
                    bbox = list(to_shape(item.geom).bounds)
                    scenes.append(
                        SentinelScene(
                            id=item.id,
                            datetime=item.datetime,
                            cloud_cover=item.cloud_cover,
                            red_band_url=assets.get("red"),
                            nir_band_url=assets.get("nir"),
                            blue_band_url=assets.get("blue"),
                            green_band_url=assets.get("green"),
                            red_edge_band_url=assets.get("red_edge"),
                            swir1_band_url=assets.get("swir1"),
                            bbox=bbox,
                        )
                    )

                return scenes
        except Exception as e:
            logger.error(f"Error reading from STAC cache: {e}")
            return None

    @staticmethod
    def cache_search_results(
        search_geom: dict,
        start_date: datetime,
        end_date: datetime,
        max_cloud_cover: float,
        scenes: List[SentinelScene],
    ) -> None:
        """
        Cache the scenes returned from Earth Search and log the search footprint.
        """
        shapely_search_geom = shape(search_geom)
        postgis_search_geom = from_shape(shapely_search_geom, srid=4326)

        try:
            with get_db_session() as db:
                # Upsert scenes
                for scene in scenes:
                    # Earth Search provides bbox, construct polygon bounds
                    if not scene.bbox:
                        continue
                    
                    minx, miny, maxx, maxy = scene.bbox
                    scene_polygon = {
                        "type": "Polygon",
                        "coordinates": [[
                            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]
                        ]]
                    }
                    scene_postgis = from_shape(shape(scene_polygon), srid=4326)

                    assets = {
                        "red": scene.red_band_url,
                        "nir": scene.nir_band_url,
                        "blue": scene.blue_band_url,
                        "green": scene.green_band_url,
                        "red_edge": scene.red_edge_band_url,
                        "swir1": scene.swir1_band_url,
                    }

                    existing = db.query(STACSceneCache).filter(STACSceneCache.id == scene.id).first()
                    if not existing:
                        new_scene = STACSceneCache(
                            id=scene.id,
                            geom=scene_postgis,
                            datetime=scene.datetime,
                            cloud_cover=scene.cloud_cover,
                            assets=assets,
                        )
                        db.add(new_scene)

                # Record the search region
                new_region = STACSearchRegion(
                    geom=postgis_search_geom,
                    start_date=start_date,
                    end_date=end_date,
                    max_cloud_cover=max_cloud_cover,
                )
                db.add(new_region)
                logger.debug("Saved search footprint and caching %d scenes to DB.", len(scenes))
        except Exception as e:
            logger.error(f"Error saving to STAC cache: {e}")
