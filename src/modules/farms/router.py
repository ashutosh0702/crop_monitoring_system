"""
Farm management router with PostgreSQL/PostGIS database.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import List

from src.database import get_db
from src.core import security
from src.modules.crops.ndvi_service import NDVILogic
from src.models import User
from . import schemas, services


router = APIRouter(prefix="/fields", tags=["Farms"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# Initialize NDVI engine (use_mock=True for development)
ndvi_engine = NDVILogic(use_mock=True)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """
    Dependency to get current authenticated user from JWT token.
    
    Returns:
        User object from database
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    try:
        payload = security.jwt.decode(
            token,
            security.settings.SECRET_KEY,
            algorithms=[security.settings.ALGORITHM]
        )
        phone = payload.get("sub")
        if phone is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.phone_number == phone).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    return user


@router.post("/", response_model=schemas.FieldResponse)
async def add_field_and_analyze(
    field: schemas.FieldCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create a new farm field and trigger NDVI analysis.
    
    - **name**: Name of the field
    - **boundary**: GeoJSON Polygon of the field boundary
    
    Returns the field with initial NDVI analysis results.
    """
    farm_service = services.FarmService(db)
    
    # Create the field
    new_farm = farm_service.create_field(str(current_user.id), field)
    farm_id = str(new_farm.id)
    
    # Trigger NDVI Analysis
    analysis_results = await ndvi_engine.process_field_ndvi(
        user_id=str(current_user.id),
        farm_id=farm_id,
        geojson_boundary=field.boundary.dict()
    )
    
    # Store results in database
    updated_farm = farm_service.attach_analysis(
        field_id=farm_id,
        analysis_results=analysis_results
    )
    
    return updated_farm


@router.get("/", response_model=List[schemas.FieldResponse])
def get_fields(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get all farms owned by the current user.
    
    Returns a list of fields with their latest analysis data.
    """
    farm_service = services.FarmService(db)
    return farm_service.get_my_fields(str(current_user.id))


@router.get("/{farm_id}/history", response_model=List[schemas.NDVIAnalysis])
def get_farm_history(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Get NDVI analysis history for a specific farm.
    
    Returns the full timeline of NDVI scans for plotting health trends.
    """
    farm_service = services.FarmService(db)
    
    # Verify ownership
    farm = farm_service.get_field_by_id(farm_id, str(current_user.id))
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    return farm_service.get_analysis_history(farm_id)


@router.post("/{farm_id}/analyze", response_model=schemas.NDVIAnalysis)
async def trigger_analysis(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Trigger a new NDVI analysis for an existing farm.
    
    Use this to refresh analysis with latest satellite imagery.
    """
    farm_service = services.FarmService(db)
    
    # Get farm and verify ownership
    farm = farm_service.get_field_by_id(farm_id, str(current_user.id))
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    # Get boundary as GeoJSON
    from geoalchemy2.shape import to_shape
    from shapely.geometry import mapping
    
    shapely_geom = to_shape(farm.boundary)
    boundary_geojson = mapping(shapely_geom)
    
    # Run NDVI analysis
    analysis_results = await ndvi_engine.process_field_ndvi(
        user_id=str(current_user.id),
        farm_id=farm_id,
        geojson_boundary=boundary_geojson
    )
    
    # Store results
    updated_farm = farm_service.attach_analysis(
        field_id=farm_id,
        analysis_results=analysis_results
    )
    
    return updated_farm.get("latest_analysis")