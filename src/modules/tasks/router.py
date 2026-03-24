"""
Task management router for background jobs.
"""

from typing import List

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from src.celery_app import celery_app
from src.database import get_db
from src.models import Farm, User
from src.modules.auth.dependencies import get_current_user
from src.modules.tasks import schemas
from src.tasks import check_alerts, generate_farm_report, process_ndvi_task, scan_all_farms

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/status/{task_id}", response_model=schemas.TaskStatusResponse)
def get_task_status(task_id: str):
    """Get the current status of a Celery task."""
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
    db: Session = Depends(get_db),
):
    """Queue NDVI analysis for a specific farm."""
    farm = (
        db.query(Farm)
        .filter(Farm.id == farm_id, Farm.owner_id == current_user.id)
        .first()
    )
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found",
        )

    boundary_geojson = mapping(to_shape(farm.boundary))
    task = process_ndvi_task.delay(
        farm_id=str(farm.id),
        user_id=str(current_user.id),
        boundary_geojson=boundary_geojson,
    )
    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"NDVI analysis queued for farm '{farm.name}'",
        "check_status_url": f"/tasks/status/{task.id}",
    }


@router.post("/report/{farm_id}", response_model=schemas.ReportTaskResponse)
def trigger_farm_report(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue a report generation task for a specific farm."""
    farm = (
        db.query(Farm)
        .filter(Farm.id == farm_id, Farm.owner_id == current_user.id)
        .first()
    )
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found",
        )

    task = generate_farm_report.delay(farm_id=str(farm.id))
    return {
        "task_id": task.id,
        "status": "queued",
        "farm_id": farm_id,
        "message": f"Report generation queued for farm '{farm.name}'",
    }


@router.post("/scan-all", response_model=schemas.TaskTriggerResponse)
def trigger_scan_all(
    current_user: User = Depends(get_current_user),
):
    """Queue NDVI scans for the current user's farms."""
    task = scan_all_farms.delay(str(current_user.id))
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Farm scan triggered for your farms",
        "check_status_url": f"/tasks/status/{task.id}",
    }


@router.post("/check-alerts", response_model=schemas.TaskTriggerResponse)
def trigger_alert_check(
    current_user: User = Depends(get_current_user),
):
    """Queue alert evaluation for the current user's farms."""
    task = check_alerts.delay(str(current_user.id))
    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Alert check triggered for your farms",
        "check_status_url": f"/tasks/status/{task.id}",
    }


@router.get("/active", response_model=List[schemas.TaskStatusResponse])
def get_active_tasks(
    current_user: User = Depends(get_current_user),
):
    """Return active or queued Celery tasks visible from worker inspect."""
    inspect = celery_app.control.inspect()
    tasks = []
    active = inspect.active() or {}
    reserved = inspect.reserved() or {}
    scheduled = inspect.scheduled() or {}

    for worker, worker_tasks in {**active, **reserved, **scheduled}.items():
        for task in worker_tasks:
            tasks.append(
                {
                    "task_id": task.get("id", "unknown"),
                    "status": "running" if worker in active else "queued",
                    "result": None,
                    "error": None,
                }
            )

    return tasks
