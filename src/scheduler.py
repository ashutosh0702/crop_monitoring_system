"""
APScheduler setup for periodic forward fill and monitoring tasks.

Handles scheduling of recurring jobs like:
- Forward fill: Every 3-5 days, fetch latest Sentinel-2 for all farms
- Alert checks: Monitor NDVI trends
- Farm scans: Batch process analytics

Configuration can be switched between APScheduler and Celery Beat.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import settings
from src.database import get_db_session
from src.models import Farm

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = None


def forward_fill_indices() -> dict:
    """
    Forward fill: Query latest Sentinel-2 scenes for farms not analyzed in 3-5 days.
    
    This function is reusable for both APScheduler and Celery Beat.
    
    Returns:
        Dictionary with status, farms_processed, and results
    """
    logger.info("🌾 Starting forward fill job: searching for new satellite scenes...")
    
    try:
        from geoalchemy2.shape import to_shape
        from shapely.geometry import mapping
        from src.modules.crops.indices_service import get_indices_service
        from src.modules.crops.stack_service import CropIndexStackService
        
        indices_service = get_indices_service(use_mock=settings.SATELLITE_USE_MOCK_DATA)
        
        farms_processed = 0
        farms_with_data = 0
        errors = []
        
        with get_db_session() as db:
            # Query farms that haven't been analyzed in 3+ days (or never analyzed)
            cutoff_date = datetime.now() - timedelta(days=3)
            farms = db.query(Farm).filter(
                (Farm.last_analyzed_date.is_(None)) | (Farm.last_analyzed_date < cutoff_date)
            ).all()
            
            logger.info(f"Found {len(farms)} farms due for forward fill")
            
            for farm in farms:
                try:
                    boundary_geojson = mapping(to_shape(farm.boundary))
                    
                    # Fetch latest scene(s) and compute indices
                    result = indices_service.build_index_stacks(
                        user_id=str(farm.owner_id),
                        farm_id=str(farm.id),
                        geojson_boundary=boundary_geojson,
                        max_scenes=1,  # Just latest scene
                    )
                    
                    if result.get("status") == "NO_SATELLITE_DATA":
                        logger.debug(f"No satellite data for farm {farm.id}")
                        continue
                    
                    # Persist the stack
                    stack_service = CropIndexStackService(db)
                    persisted = stack_service.save_many(farm.id, result["stacks"])
                    
                    if persisted:
                        # Update farm's last_analyzed_date
                        farm.last_analyzed_date = datetime.now()
                        db.commit()
                        farms_with_data += 1
                        logger.info(f"✅ Farm {farm.id} ({farm.name}): {len(persisted)} stacks added")
                    
                    farms_processed += 1
                    
                except Exception as exc:
                    error_msg = f"Farm {farm.id}: {str(exc)}"
                    logger.error(f"❌ {error_msg}")
                    errors.append(error_msg)
        
        return {
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "farms_processed": farms_processed,
            "farms_with_new_data": farms_with_data,
            "errors": errors,
        }
    
    except Exception as exc:
        logger.error(f"Forward fill job failed: {exc}")
        return {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "message": str(exc),
        }


def check_farm_alerts() -> dict:
    """
    Check NDVI drop alerts and other monitoring conditions.
    Reusable for both APScheduler and Celery Beat.
    
    Returns:
        Dictionary with status and alerts created
    """
    logger.info("🚨 Starting alert check job...")
    
    try:
        from src.models import Alert, NDVIAnalysis
        
        alerts_created = 0
        ndvi_threshold = 0.15  # Alert if mean_ndvi drops below this
        
        with get_db_session() as db:
            farms = db.query(Farm).all()
            
            for farm in farms:
                # Get latest analysis
                latest = db.query(NDVIAnalysis)\
                    .filter(NDVIAnalysis.farm_id == farm.id)\
                    .order_by(NDVIAnalysis.created_at.desc())\
                    .first()
                
                if not latest:
                    continue
                
                # Check if NDVI is critically low
                if latest.mean_ndvi is not None and latest.mean_ndvi < ndvi_threshold:
                    # Check if alert already exists today
                    today = datetime.now().date()
                    existing_alert = db.query(Alert)\
                        .filter(
                            Alert.farm_id == farm.id,
                            Alert.alert_type == "NDVI_DROP",
                            Alert.created_at >= datetime.combine(today, datetime.min.time()),
                        )\
                        .first()
                    
                    if not existing_alert:
                        alert = Alert(
                            farm_id=farm.id,
                            alert_type="NDVI_DROP",
                            severity="HIGH" if latest.mean_ndvi < 0.1 else "MEDIUM",
                            message=f"NDVI dropped to {latest.mean_ndvi:.3f} for {farm.name}",
                        )
                        db.add(alert)
                        alerts_created += 1
            
            db.commit()
        
        logger.info(f"✅ Alert check completed: {alerts_created} new alerts")
        return {
            "status": "completed",
            "timestamp": datetime.now().isoformat(),
            "alerts_created": alerts_created,
        }
    
    except Exception as exc:
        logger.error(f"Alert check job failed: {exc}")
        return {
            "status": "error",
            "timestamp": datetime.now().isoformat(),
            "message": str(exc),
        }


def init_scheduler():
    """
    Initialize and start the APScheduler.
    Called during FastAPI startup.
    """
    global scheduler
    
    if scheduler is not None and scheduler.running:
        logger.info("Scheduler already running")
        return
    
    logger.info("🚀 Initializing APScheduler...")
    
    scheduler = BackgroundScheduler(daemon=True)
    
    # Forward fill every 3 days (for MVP)
    scheduler.add_job(
        forward_fill_indices,
        trigger=IntervalTrigger(days=3),
        id="forward_fill_job",
        name="Forward fill satellite indices every 3 days",
        replace_existing=True,
        max_instances=1,  # Prevent concurrent runs
    )
    logger.info("📅 Scheduled: forward_fill_indices every 3 days")
    
    # Alert check every 24 hours
    scheduler.add_job(
        check_farm_alerts,
        trigger=IntervalTrigger(hours=24),
        id="alert_check_job",
        name="Check NDVI drop alerts daily",
        replace_existing=True,
        max_instances=1,
    )
    logger.info("📅 Scheduled: check_farm_alerts every 24 hours")
    
    try:
        scheduler.start()
        logger.info("✅ APScheduler started successfully")
    except Exception as exc:
        logger.error(f"Failed to start scheduler: {exc}")
        raise


def shutdown_scheduler():
    """
    Gracefully shutdown the scheduler.
    Called during FastAPI shutdown.
    """
    global scheduler
    
    if scheduler and scheduler.running:
        logger.info("Shutting down APScheduler...")
        scheduler.shutdown()
        logger.info("✅ APScheduler stopped")


def get_scheduler_status() -> dict:
    """
    Get current scheduler status and job information.
    Useful for monitoring and debugging.
    """
    if scheduler is None or not scheduler.running:
        return {
            "status": "not_running",
            "jobs": []
        }
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run_time": str(job.next_run_time),
            "trigger": str(job.trigger),
        })
    
    return {
        "status": "running",
        "jobs": jobs,
    }
