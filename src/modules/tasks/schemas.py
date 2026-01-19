"""
Pydantic schemas for task API responses.
"""

from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class TaskStatusResponse(BaseModel):
    """Response for task status check."""
    task_id: str
    status: str = Field(..., description="pending, started, success, failure, retry")
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskTriggerResponse(BaseModel):
    """Response when a background task is triggered."""
    task_id: str
    status: str = "queued"
    message: str
    check_status_url: str


class NDVITaskRequest(BaseModel):
    """Request to trigger NDVI analysis."""
    farm_id: str


class ReportTaskResponse(BaseModel):
    """Response for farm report generation."""
    task_id: str
    status: str
    farm_id: str
    message: str


class ScheduledTaskInfo(BaseModel):
    """Information about scheduled tasks."""
    name: str
    schedule: str
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    enabled: bool = True
