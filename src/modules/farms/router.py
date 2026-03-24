"""
Farm management router with threaded NDVI execution.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from src.config import settings
from src.database import get_db
from src.models import User
from src.modules.auth.dependencies import get_current_user
from src.modules.crops.ndvi_service import NDVILogic
from . import schemas, services

router = APIRouter(prefix="/fields", tags=["Farms"])

ndvi_engine = NDVILogic(use_mock=settings.SATELLITE_USE_MOCK_DATA)


@router.post("/", response_model=schemas.FieldResponse)
async def add_field_and_analyze(
    field: schemas.FieldCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Create a new farm field and run its initial NDVI analysis.
    """
    farm_service = services.FarmService(db)
    new_farm = farm_service.create_field(str(current_user.id), field)
    farm_id = str(new_farm.id)

    analysis_results = await run_in_threadpool(
        ndvi_engine.process_field_ndvi,
        str(current_user.id),
        farm_id,
        field.boundary.model_dump(),
    )
    return farm_service.attach_analysis(
        field_id=farm_id,
        analysis_results=analysis_results,
    )


@router.get("/", response_model=List[schemas.FieldResponse])
def get_fields(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all farms owned by the current user with only their latest analysis.
    """
    farm_service = services.FarmService(db)
    return farm_service.get_my_fields(str(current_user.id))


@router.get("/{farm_id}/history", response_model=List[schemas.NDVIAnalysis])
def get_farm_history(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the NDVI analysis history for a farm.
    """
    farm_service = services.FarmService(db)
    farm = farm_service.get_field_by_id(farm_id, str(current_user.id))
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found",
        )

    return farm_service.get_analysis_history(farm_id)


@router.post("/{farm_id}/analyze", response_model=schemas.NDVIAnalysis)
async def trigger_analysis(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Trigger a new NDVI analysis for an existing farm.
    """
    farm_service = services.FarmService(db)
    farm = farm_service.get_field_by_id(farm_id, str(current_user.id))
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found",
        )

    shapely_geom = to_shape(farm.boundary)
    boundary_geojson = mapping(shapely_geom)

    analysis_results = await run_in_threadpool(
        ndvi_engine.process_field_ndvi,
        str(current_user.id),
        farm_id,
        boundary_geojson,
    )
    updated_farm = farm_service.attach_analysis(
        field_id=farm_id,
        analysis_results=analysis_results,
    )
    return updated_farm.get("latest_analysis")
