"""
Celery tasks for background processing with S3 storage integration.
"""

import uuid
import logging
from datetime import datetime
from typing import Dict, Any

from celery import shared_task
from src.celery_app import celery_app
from src.database import get_db_session

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_ndvi_task(self, farm_id: str, user_id: str, boundary_geojson: dict) -> Dict[str, Any]:
    """
    Background task for NDVI calculation.
    
    Args:
        farm_id: UUID of the farm
        user_id: UUID of the user
        boundary_geojson: GeoJSON polygon of farm boundary
    
    Returns:
        Analysis results dictionary with task status
    """
    task_id = self.request.id
    logger.info(f"Starting NDVI task {task_id} for farm {farm_id}")
    
    try:
        # Import here to avoid circular imports
        from src.modules.crops.ndvi_service import NDVILogic
        from src.models import NDVIAnalysis, Farm
        
        ndvi_engine = NDVILogic(use_mock=True)  # Set to False for production
        
        # Process NDVI (async -> sync context)
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                ndvi_engine.process_field_ndvi(
                    user_id=user_id,
                    farm_id=farm_id,
                    geojson_boundary=boundary_geojson
                )
            )
        finally:
            loop.close()
        
        # Store results in database
        with get_db_session() as db:
            farm = db.query(Farm).filter(Farm.id == farm_id).first()
            if not farm:
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
            )
            db.add(analysis)
            db.commit()
            
            logger.info(f"NDVI task {task_id} completed for farm {farm_id}")
            
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
                }
            }
        
    except Exception as exc:
        logger.error(f"NDVI task {task_id} failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120)
def fetch_satellite_imagery_task(self, farm_id: str, bbox: list) -> Dict[str, Any]:
    """
    Background task to fetch satellite imagery from STAC API.
    
    Args:
        farm_id: UUID of the farm
        bbox: Bounding box [minx, miny, maxx, maxy]
    
    Returns:
        Dictionary with imagery URLs and metadata
    """
    task_id = self.request.id
    logger.info(f"Starting satellite fetch task {task_id} for farm {farm_id}")
    
    try:
        from src.modules.crops.stac_client import get_stac_client
        
        client = get_stac_client(use_mock=False)
        
        # Create geometry from bbox
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
            ]]
        }
        
        scenes = client.search_scenes(
            geometry=geometry,
            max_cloud_cover=30.0,
            limit=5
        )
        
        if not scenes:
            return {
                "status": "no_data",
                "message": "No satellite scenes found for this location"
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
            }
        }
        
    except Exception as exc:
        logger.error(f"Satellite fetch task {task_id} failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task
def scan_all_farms() -> Dict[str, Any]:
    """
    Scheduled task to scan all active farms for updated NDVI.
    Called by Celery Beat on schedule.
    
    Returns:
        Summary of farms scanned and tasks queued
    """
    logger.info("Starting scheduled farm scan")
    
    try:
        from src.models import Farm
        from geoalchemy2.shape import to_shape
        from shapely.geometry import mapping
        
        farms_queued = 0
        
        with get_db_session() as db:
            # Get all farms
            farms = db.query(Farm).all()
            
            for farm in farms:
                # Get boundary as GeoJSON
                shapely_geom = to_shape(farm.boundary)
                boundary_geojson = mapping(shapely_geom)
                
                # Queue NDVI task
                process_ndvi_task.delay(
                    farm_id=str(farm.id),
                    user_id=str(farm.owner_id),
                    boundary_geojson=boundary_geojson
                )
                farms_queued += 1
        
        logger.info(f"Scheduled scan queued {farms_queued} farms")
        
        return {
            "status": "completed",
            "farms_scanned": farms_queued,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Scheduled scan failed: {exc}")
        return {"status": "error", "message": str(exc)}


@celery_app.task
def check_alerts() -> Dict[str, Any]:
    """
    Check farms for NDVI drops and generate alerts.
    Compares latest analysis with previous to detect significant changes.
    """
    logger.info("Starting alert check")
    
    try:
        from src.models import Farm, NDVIAnalysis, Alert
        
        alerts_created = 0
        NDVI_DROP_THRESHOLD = 0.15  # Alert if NDVI drops more than this
        
        with get_db_session() as db:
            farms = db.query(Farm).all()
            
            for farm in farms:
                analyses = db.query(NDVIAnalysis).filter(
                    NDVIAnalysis.farm_id == farm.id
                ).order_by(NDVIAnalysis.created_at.desc()).limit(2).all()
                
                if len(analyses) < 2:
                    continue  # Need at least 2 analyses to compare
                
                latest = analyses[0]
                previous = analyses[1]
                
                ndvi_change = previous.mean_ndvi - latest.mean_ndvi
                
                if ndvi_change > NDVI_DROP_THRESHOLD:
                    # Significant NDVI drop - create alert
                    alert = Alert(
                        id=uuid.uuid4(),
                        farm_id=farm.id,
                        alert_type="NDVI_DROP",
                        severity="HIGH" if ndvi_change > 0.25 else "MEDIUM",
                        message=f"NDVI dropped by {ndvi_change:.2f} from {previous.mean_ndvi:.2f} to {latest.mean_ndvi:.2f}",
                        is_read=False,
                    )
                    db.add(alert)
                    alerts_created += 1
            
            db.commit()
        
        logger.info(f"Alert check created {alerts_created} alerts")
        
        return {
            "status": "completed",
            "alerts_created": alerts_created,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as exc:
        logger.error(f"Alert check failed: {exc}")
        return {"status": "error", "message": str(exc)}


@celery_app.task
def generate_farm_report(farm_id: str) -> Dict[str, Any]:
    """
    Generate a comprehensive report for a farm.
    Includes NDVI trends, weather data, and recommendations.
    """
    logger.info(f"Generating report for farm {farm_id}")
    
    try:
        from src.models import Farm, NDVIAnalysis
        from src.modules.weather.weather_client import get_weather_client
        from geoalchemy2.shape import to_shape
        import asyncio
        
        with get_db_session() as db:
            farm = db.query(Farm).filter(Farm.id == farm_id).first()
            if not farm:
                return {"status": "error", "message": "Farm not found"}
            
            # Get NDVI history
            analyses = db.query(NDVIAnalysis).filter(
                NDVIAnalysis.farm_id == farm.id
            ).order_by(NDVIAnalysis.created_at.desc()).limit(10).all()
            
            # Get farm centroid for weather
            shapely_geom = to_shape(farm.boundary)
            centroid = shapely_geom.centroid
            
            # Fetch weather
            weather_client = get_weather_client()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                current = loop.run_until_complete(
                    weather_client.get_current_weather(centroid.y, centroid.x)
                )
                forecast = loop.run_until_complete(
                    weather_client.get_forecast(centroid.y, centroid.x, 5)
                )
            finally:
                loop.close()
            
            # Generate insights
            insights = weather_client.get_agricultural_insights(current, forecast)
            
            return {
                "status": "completed",
                "farm_id": farm_id,
                "farm_name": farm.name,
                "area_acres": farm.area_acres,
                "ndvi_history": [
                    {"date": a.created_at.isoformat(), "mean_ndvi": a.mean_ndvi, "status": a.status}
                    for a in analyses
                ],
                "current_weather": {
                    "temperature": current.temperature,
                    "humidity": current.humidity,
                    "description": current.description,
                },
                "recommendations": insights.get("recommendations", []),
                "generated_at": datetime.utcnow().isoformat()
            }
        
    except Exception as exc:
        logger.error(f"Report generation failed: {exc}")
        return {"status": "error", "message": str(exc)}
