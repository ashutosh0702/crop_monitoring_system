"""
Crops router for persisted vegetation index stacks.
"""

from datetime import datetime
from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping

from src.config import settings
from src.database import get_db
from src.models import Farm, User
from src.modules.auth.dependencies import get_current_user
from src.modules.crops import schemas
from src.modules.crops.indices_service import get_indices_service
from src.modules.crops.stack_service import CropIndexStackService
from src.tasks import build_index_stacks_task

router = APIRouter(prefix="/crops", tags=["Crop Analysis"])


def get_farm_boundary(farm_id: str, user_id: str, db: Session) -> Tuple[dict, Farm]:
    """Get farm boundary as GeoJSON while enforcing ownership."""
    farm = (
        db.query(Farm)
        .filter(Farm.id == farm_id, Farm.owner_id == user_id)
        .first()
    )
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found",
        )

    shapely_geom = to_shape(farm.boundary)
    return mapping(shapely_geom), farm


async def ensure_latest_stack(
    farm_id: str,
    user_id: str,
    boundary_geojson: dict,
    db: Session,
    refresh: bool = False,
):
    """Return the latest persisted stack or compute and store it."""
    stack_service = CropIndexStackService(db)
    if not refresh:
        latest = stack_service.get_latest_stack(farm_id)
        if latest is not None:
            return latest

    indices_service = get_indices_service(use_mock=settings.SATELLITE_USE_MOCK_DATA)
    result = await run_in_threadpool(
        indices_service.process_all_indices,
        user_id,
        farm_id,
        boundary_geojson,
    )
    if result.get("status") == "NO_SATELLITE_DATA":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No satellite imagery available for this location",
        )

    return stack_service.save_stack(farm_id, result)


@router.get("/indices/{farm_id}", response_model=schemas.AllIndicesResponse)
async def get_all_indices(
    farm_id: str,
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the latest persisted multi-index stack for a farm."""
    boundary_geojson, _ = get_farm_boundary(farm_id, str(current_user.id), db)
    return await ensure_latest_stack(
        farm_id=farm_id,
        user_id=str(current_user.id),
        boundary_geojson=boundary_geojson,
        db=db,
        refresh=refresh,
    )


@router.get("/stacks/{farm_id}", response_model=List[schemas.AllIndicesResponse])
def list_index_stacks(
    farm_id: str,
    limit: int = Query(default=10, ge=1, le=25),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List persisted historical index stacks for a farm."""
    get_farm_boundary(farm_id, str(current_user.id), db)
    stack_service = CropIndexStackService(db)
    return stack_service.list_stacks(farm_id, limit=limit)


@router.post("/stacks/{farm_id}")
def queue_index_stack_build(
    farm_id: str,
    max_scenes: int = Query(default=settings.INDEX_STACK_SCENE_LIMIT, ge=1, le=20),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Queue background historical stack generation for a farm."""
    boundary_geojson, farm = get_farm_boundary(farm_id, str(current_user.id), db)
    task = build_index_stacks_task.delay(
        farm_id=str(farm.id),
        user_id=str(current_user.id),
        boundary_geojson=boundary_geojson,
        max_scenes=max_scenes,
    )
    return {
        "task_id": task.id,
        "status": "queued",
        "message": f"Index stack build queued for farm '{farm.name}'",
        "check_status_url": f"/tasks/status/{task.id}",
    }


@router.get("/ndmi/{farm_id}", response_model=schemas.NDMIResponse)
async def get_ndmi(
    farm_id: str,
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the latest NDMI result for a farm."""
    boundary_geojson, _ = get_farm_boundary(farm_id, str(current_user.id), db)
    latest_stack = await ensure_latest_stack(
        farm_id=farm_id,
        user_id=str(current_user.id),
        boundary_geojson=boundary_geojson,
        db=db,
        refresh=refresh,
    )
    ndmi_result = latest_stack["indices"]["NDMI"]

    recommendations = []
    if ndmi_result["mean"] is not None:
        if ndmi_result["mean"] < 0:
            recommendations.append("Water stress detected - consider immediate irrigation")
        elif ndmi_result["mean"] < 0.2:
            recommendations.append("Moderate moisture - monitor closely")
        else:
            recommendations.append("Good moisture levels")

    return {
        "farm_id": farm_id,
        "timestamp": datetime.fromisoformat(latest_stack["timestamp"]),
        "scene_date": datetime.fromisoformat(latest_stack["scene_date"]),
        "ndmi": ndmi_result,
        "moisture_recommendations": recommendations,
        "stack_tiff_url": latest_stack["stack_tiff_url"],
    }


@router.get("/ndwi/{farm_id}", response_model=schemas.NDMIResponse, deprecated=True)
async def get_ndwi_alias(
    farm_id: str,
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Backward-compatible alias for the NDMI moisture view."""
    return await get_ndmi(
        farm_id=farm_id,
        refresh=refresh,
        current_user=current_user,
        db=db,
    )


@router.get("/evi/{farm_id}", response_model=schemas.EVIResponse)
async def get_evi(
    farm_id: str,
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get the latest EVI result for a farm."""
    boundary_geojson, _ = get_farm_boundary(farm_id, str(current_user.id), db)
    latest_stack = await ensure_latest_stack(
        farm_id=farm_id,
        user_id=str(current_user.id),
        boundary_geojson=boundary_geojson,
        db=db,
        refresh=refresh,
    )
    evi_result = latest_stack["indices"]["EVI"]

    if evi_result["mean"] is not None:
        if evi_result["mean"] > 0.4:
            analysis = "Healthy dense vegetation"
        elif evi_result["mean"] > 0.2:
            analysis = "Moderate vegetation coverage"
        else:
            analysis = "Low vegetation density"
    else:
        analysis = "Unable to analyze"

    return {
        "farm_id": farm_id,
        "timestamp": datetime.fromisoformat(latest_stack["timestamp"]),
        "scene_date": datetime.fromisoformat(latest_stack["scene_date"]),
        "evi": evi_result,
        "vegetation_analysis": analysis,
        "stack_tiff_url": latest_stack["stack_tiff_url"],
    }


@router.get("/compare/{farm_id}")
async def compare_indices(
    farm_id: str,
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare the latest index stack side-by-side."""
    boundary_geojson, farm = get_farm_boundary(farm_id, str(current_user.id), db)
    latest_stack = await ensure_latest_stack(
        farm_id=farm_id,
        user_id=str(current_user.id),
        boundary_geojson=boundary_geojson,
        db=db,
        refresh=refresh,
    )
    return {
        "farm_id": farm_id,
        "farm_name": farm.name,
        "timestamp": latest_stack["timestamp"],
        "scene_date": latest_stack["scene_date"],
        "indices": latest_stack["indices"],
        "summary": latest_stack["summary"],
        "source": latest_stack["source"],
        "stack_tiff_url": latest_stack["stack_tiff_url"],
        "band_order": latest_stack["band_order"],
    }
