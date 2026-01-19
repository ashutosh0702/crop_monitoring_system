"""
Celery application configuration for background task processing.
"""

from celery import Celery
from celery.schedules import crontab
from src.config import settings

# Create Celery app
celery_app = Celery(
    "crop_monitoring",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.tasks"],  # Include task modules
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task execution settings
    task_track_started=True,
    task_time_limit=600,  # 10 minutes max per task
    task_soft_time_limit=540,  # Soft limit at 9 minutes
    
    # Result backend settings
    result_expires=3600,  # Results expire after 1 hour
    
    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time for heavy processing
    worker_concurrency=2,  # Number of concurrent workers
    
    # Retry settings
    task_acks_late=True,  # Acknowledge after completion
    task_reject_on_worker_lost=True,  # Requeue if worker dies
    
    # Beat scheduler for automated scanning
    beat_schedule={
        # Scan all farms daily at 6 AM UTC
        "scan-all-farms-daily": {
            "task": "src.tasks.scan_all_farms",
            "schedule": crontab(hour=6, minute=0),
            "options": {"queue": "ndvi_processing"},
        },
        # Check for NDVI drops and create alerts every 6 hours
        "check-alerts-every-6h": {
            "task": "src.tasks.check_alerts",
            "schedule": crontab(hour="*/6", minute=30),
        },
    },
)

# Task routing for different queues
celery_app.conf.task_routes = {
    "src.tasks.process_ndvi_task": {"queue": "ndvi_processing"},
    "src.tasks.fetch_satellite_imagery_task": {"queue": "satellite"},
    "src.tasks.generate_farm_report": {"queue": "reports"},
}

