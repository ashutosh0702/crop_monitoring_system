"""
Task management router for background job status and triggering.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import List
from celery.result import AsyncResult

from src.database import get_db
from src.celery_app import celery_app
from src.models import User, Farm
from src.tasks import process_ndvi_task, generate_farm_report, scan_all_farms, check_alerts
from src.modules.tasks import schemas

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping


router = APIRouter(prefix="/tasks", tags=["Tasks"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token."""
    from src.core import security
    
    try:
        payload = security.jwt.decode(
            token,
            security.settings.SECRET_KEY,
            algorithms=[security.settings.ALGORITHM]
        )
        phone = payload.get("sub")
        if phone is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.phone_number == phone).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


@router.get("/status/{task_id}", response_model=schemas.TaskStatusResponse)
def get_task_status(task_id: str):
    """
    Get the status of a background task.
    
    - **task_id**: Celery task ID returned when task was triggered
    
    Returns task status: pending, started, success, failure, retry
    """
    result = AsyncResult(task_id, app=celery_app)
    
    response = {
        "task_id": task_id,
        "status": result.status.lower(),
        "result": None,
        "error": None,
    }
    
    if result.ready():
        if result.successful():
            response["result"] = result.get()
        else:
            response["error"] = str(result.result)
    
    return response


@router.post("/analyze/{farm_id}", response_model=schemas.TaskTriggerResponse)
def trigger_ndvi_analysis(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Trigger background NDVI analysis for a farm.
    
    This is the async version - returns immediately with a task_id
    that can be used to check progress via GET /tasks/status/{task_id}
    """
    # Verify farm ownership
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == current_user.id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    # Get boundary as GeoJSON
    shapely_geom = to_shape(farm.boundary)
    boundary_geojson = mapping(shapely_geom)
    
    # Queue the task
    task = process_ndvi_task.delay(
        farm_id=str(farm.id),
        user_id=str(current_user.id),
        boundary_geojson=boundary_geojson
    )
    
    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"NDVI analysis queued for farm '{farm.name}'",
        "check_status_url": f"/tasks/status/{task.id}"
    }


@router.post("/report/{farm_id}", response_model=schemas.ReportTaskResponse)
def trigger_farm_report(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Trigger background report generation for a farm.
    
    Generates a comprehensive report with NDVI trends,
    weather data, and recommendations.
    """
    # Verify farm ownership
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == current_user.id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    # Queue the report task
    task = generate_farm_report.delay(farm_id=str(farm.id))
    
    return {
        "task_id": task.id,
        "status": "queued",
        "farm_id": farm_id,
        "message": f"Report generation queued for farm '{farm.name}'"
    }


@router.post("/scan-all", response_model=schemas.TaskTriggerResponse)
def trigger_scan_all(
    current_user: User = Depends(get_current_user),
):
    """
    Trigger a scan of all farms owned by the user.
    
    Queues NDVI analysis for all farms in the background.
    Note: In production, this would be restricted to admins.
    """
    task = scan_all_farms.delay()
    
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Farm scan triggered for all farms",
        "check_status_url": f"/tasks/status/{task.id}"
    }


@router.post("/check-alerts", response_model=schemas.TaskTriggerResponse)
def trigger_alert_check(
    current_user: User = Depends(get_current_user),
):
    """
    Trigger an alert check across all farms.
    
    Checks for NDVI drops and creates alerts as needed.
    """
    task = check_alerts.delay()
    
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Alert check triggered",
        "check_status_url": f"/tasks/status/{task.id}"
    }


@router.get("/active", response_model=List[schemas.TaskStatusResponse])
def get_active_tasks(
    current_user: User = Depends(get_current_user),
):
    """
    Get list of active/pending tasks.
    
    Note: This requires Celery result backend with task tracking.
    Currently returns basic info.
    """
    # Get active tasks from Celery inspect
    inspect = celery_app.control.inspect()
    
    tasks = []
    
    # Get scheduled, active, and reserved tasks
    active = inspect.active() or {}
    reserved = inspect.reserved() or {}
    scheduled = inspect.scheduled() or {}
    
    for worker, worker_tasks in {**active, **reserved, **scheduled}.items():
        for task in worker_tasks:
            tasks.append({
                "task_id": task.get("id", "unknown"),
                "status": "running" if worker in active else "queued",
                "result": None,
                "error": None,
            })
    
    return tasks
