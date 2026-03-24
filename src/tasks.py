"""
Celery tasks for NDVI processing, historical index stacks, alerts, and reporting.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from src.celery_app import celery_app
from src.config import settings
from src.database import get_db_session

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_ndvi_task(self, farm_id: str, user_id: str, boundary_geojson: dict) -> Dict[str, Any]:
    """Compute NDVI for a farm and persist the resulting analysis."""
    task_id = self.request.id
    logger.info("Starting NDVI task %s for farm %s", task_id, farm_id)

    try:
        from src.models import Farm, NDVIAnalysis
        from src.modules.crops.ndvi_service import NDVILogic

        ndvi_engine = NDVILogic(use_mock=settings.SATELLITE_USE_MOCK_DATA)
        result = ndvi_engine.process_field_ndvi(
            user_id=user_id,
            farm_id=farm_id,
            geojson_boundary=boundary_geojson,
        )

        with get_db_session() as db:
            farm = db.query(Farm).filter(Farm.id == farm_id).first()
            if farm is None:
                return {"status": "error", "message": "Farm not found"}

            stats = result.get("stats", {})
            metadata = result.get("metadata", {})
            analysis = NDVIAnalysis(
                id=uuid.uuid4(),
                farm_id=uuid.UUID(farm_id),
                tiff_url=result["tiff_url"],
                png_url=result.get("png_url", "placeholder"),
                mean_ndvi=stats.get("mean_ndvi", 0),
                min_ndvi=stats.get("min_ndvi"),
                max_ndvi=stats.get("max_ndvi"),
                std_ndvi=stats.get("std_ndvi"),
                status=stats.get("status", "DATA_MISSING"),
                satellite_source=metadata.get("satellite_source", "mock"),
                scene_date=_parse_datetime(metadata.get("scene_date")),
                cloud_cover=metadata.get("cloud_cover"),
            )
            db.add(analysis)
            db.flush()

            logger.info("NDVI task %s completed for farm %s", task_id, farm_id)
            return {
                "status": "completed",
                "task_id": task_id,
                "farm_id": farm_id,
                "analysis_id": str(analysis.id),
                "results": {
                    "tiff_url": result["tiff_url"],
                    "png_url": result.get("png_url"),
                    "mean_ndvi": stats.get("mean_ndvi"),
                    "status": stats.get("status"),
                },
            }
    except Exception as exc:
        logger.error("NDVI task %s failed: %s", task_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def build_index_stacks_task(
    self,
    farm_id: str,
    user_id: str,
    boundary_geojson: dict,
    max_scenes: int = 5,
) -> Dict[str, Any]:
    """Build and persist a stack of vegetation indices for recent scene dates."""
    task_id = self.request.id
    logger.info("Starting index stack task %s for farm %s", task_id, farm_id)

    try:
        from src.modules.crops.indices_service import get_indices_service
        from src.modules.crops.stack_service import CropIndexStackService

        indices_service = get_indices_service(use_mock=settings.SATELLITE_USE_MOCK_DATA)
        result = indices_service.build_index_stacks(
            user_id=user_id,
            farm_id=farm_id,
            geojson_boundary=boundary_geojson,
            max_scenes=max_scenes,
        )
        if result.get("status") == "NO_SATELLITE_DATA":
            return result

        with get_db_session() as db:
            stack_service = CropIndexStackService(db)
            persisted = stack_service.save_many(farm_id, result["stacks"])
            return {
                "status": "completed",
                "task_id": task_id,
                "farm_id": farm_id,
                "stacks_created": len(persisted),
                "scene_dates": [stack["scene_date"] for stack in persisted],
            }
    except Exception as exc:
        logger.error("Index stack task %s failed: %s", task_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def fetch_satellite_imagery_task(self, farm_id: str, bbox: list) -> Dict[str, Any]:
    """Search for recent scenes intersecting the farm bbox."""
    task_id = self.request.id
    logger.info("Starting satellite fetch task %s for farm %s", task_id, farm_id)

    try:
        from src.modules.crops.stac_client import get_stac_client

        client = get_stac_client(use_mock=settings.SATELLITE_USE_MOCK_DATA)
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
            ]],
        }
        scenes = client.search_scenes(
            geometry=geometry,
            max_cloud_cover=30.0,
            limit=5,
        )
        if not scenes:
            return {
                "status": "no_data",
                "message": "No satellite scenes found for this location",
            }

        return {
            "status": "completed",
            "task_id": task_id,
            "farm_id": farm_id,
            "scenes_found": len(scenes),
            "best_scene": {
                "id": scenes[0].id,
                "datetime": scenes[0].datetime.isoformat() if scenes[0].datetime else None,
                "cloud_cover": scenes[0].cloud_cover,
            },
        }
    except Exception as exc:
        logger.error("Satellite fetch task %s failed: %s", task_id, exc)
        raise self.retry(exc=exc)


@celery_app.task
def scan_all_farms(owner_id: Optional[str] = None) -> Dict[str, Any]:
    """Queue NDVI analysis for all farms or just one owner's farms."""
    logger.info("Starting farm scan for owner_id=%s", owner_id)

    try:
        from geoalchemy2.shape import to_shape
        from shapely.geometry import mapping
        from src.models import Farm

        farms_queued = 0
        with get_db_session() as db:
            query = db.query(Farm)
            if owner_id:
                query = query.filter(Farm.owner_id == uuid.UUID(owner_id))
            farms = query.all()

            for farm in farms:
                boundary_geojson = mapping(to_shape(farm.boundary))
                process_ndvi_task.delay(
                    farm_id=str(farm.id),
                    user_id=str(farm.owner_id),
                    boundary_geojson=boundary_geojson,
                )
                farms_queued += 1

        return {
            "status": "completed",
            "farms_scanned": farms_queued,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error("Farm scan failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@celery_app.task
def check_alerts(owner_id: Optional[str] = None) -> Dict[str, Any]:
    """Create NDVI drop alerts for all farms or one owner's farms."""
    logger.info("Starting alert check for owner_id=%s", owner_id)

    try:
        from src.models import Alert, Farm, NDVIAnalysis

        alerts_created = 0
        threshold = 0.15

        with get_db_session() as db:
            query = db.query(Farm)
            if owner_id:
                query = query.filter(Farm.owner_id == uuid.UUID(owner_id))
            farms = query.all()

            for farm in farms:
                analyses = (
                    db.query(NDVIAnalysis)
                    .filter(NDVIAnalysis.farm_id == farm.id)
                    .order_by(NDVIAnalysis.created_at.desc())
                    .limit(2)
                    .all()
                )
                if len(analyses) < 2:
                    continue

                latest = analyses[0]
                previous = analyses[1]
                ndvi_change = previous.mean_ndvi - latest.mean_ndvi
                if ndvi_change <= threshold:
                    continue

                message = (
                    f"NDVI dropped by {ndvi_change:.2f} "
                    f"from {previous.mean_ndvi:.2f} to {latest.mean_ndvi:.2f}"
                )
                existing = (
                    db.query(Alert)
                    .filter(
                        Alert.farm_id == farm.id,
                        Alert.alert_type == "NDVI_DROP",
                        Alert.message == message,
                    )
                    .first()
                )
                if existing:
                    continue

                db.add(
                    Alert(
                        id=uuid.uuid4(),
                        farm_id=farm.id,
                        alert_type="NDVI_DROP",
                        severity="HIGH" if ndvi_change > 0.25 else "MEDIUM",
                        message=message,
                        is_read=False,
                    )
                )
                alerts_created += 1

        return {
            "status": "completed",
            "alerts_created": alerts_created,
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.error("Alert check failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@celery_app.task
def generate_farm_report(farm_id: str) -> Dict[str, Any]:
    """Generate a farm report using recent NDVI history and current weather."""
    logger.info("Generating report for farm %s", farm_id)

    try:
        from geoalchemy2.shape import to_shape
        from src.models import Farm, NDVIAnalysis
        from src.modules.weather.weather_client import get_weather_client

        with get_db_session() as db:
            farm = db.query(Farm).filter(Farm.id == farm_id).first()
            if farm is None:
                return {"status": "error", "message": "Farm not found"}

            analyses = (
                db.query(NDVIAnalysis)
                .filter(NDVIAnalysis.farm_id == farm.id)
                .order_by(NDVIAnalysis.created_at.desc())
                .limit(10)
                .all()
            )

            centroid = to_shape(farm.boundary).centroid
            weather_client = get_weather_client()

            async def _load_weather():
                current_weather = await weather_client.get_current_weather(centroid.y, centroid.x)
                forecast_data = await weather_client.get_forecast(centroid.y, centroid.x, 5)
                return current_weather, forecast_data

            current, forecast = asyncio.run(_load_weather())
            insights = weather_client.get_agricultural_insights(current, forecast)

            return {
                "status": "completed",
                "farm_id": farm_id,
                "farm_name": farm.name,
                "area_acres": farm.area_acres,
                "ndvi_history": [
                    {
                        "date": analysis.created_at.isoformat(),
                        "mean_ndvi": analysis.mean_ndvi,
                        "status": analysis.status,
                    }
                    for analysis in analyses
                ],
                "current_weather": {
                    "temperature": current.temperature,
                    "humidity": current.humidity,
                    "description": current.description,
                },
                "recommendations": insights.get("recommendations", []),
                "generated_at": datetime.utcnow().isoformat(),
            }
    except Exception as exc:
        logger.error("Report generation failed: %s", exc)
        return {"status": "error", "message": str(exc)}


def _parse_datetime(value: Optional[str]):
    if not value:
        return None
    return value if hasattr(value, "isoformat") else datetime.fromisoformat(value)
