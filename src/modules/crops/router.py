"""
Crops router for vegetation indices (NDWI, EVI, etc).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime

from src.database import get_db
from src.models import User, Farm
from src.modules.crops.indices_service import get_indices_service
from src.modules.crops import schemas

from geoalchemy2.shape import to_shape
from shapely.geometry import mapping


router = APIRouter(prefix="/crops", tags=["Crop Analysis"])
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


def get_farm_boundary(farm_id: str, user_id: str, db: Session) -> tuple:
    """Get farm boundary as GeoJSON, verifying ownership."""
    farm = db.query(Farm).filter(
        Farm.id == farm_id,
        Farm.owner_id == user_id
    ).first()
    
    if not farm:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Farm not found"
        )
    
    shapely_geom = to_shape(farm.boundary)
    return mapping(shapely_geom), farm


@router.get("/indices/{farm_id}", response_model=schemas.AllIndicesResponse)
async def get_all_indices(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Calculate all vegetation indices for a farm.
    
    Returns:
    - **NDVI**: Normalized Difference Vegetation Index
    - **NDWI**: Normalized Difference Water Index (moisture)
    - **EVI**: Enhanced Vegetation Index (dense vegetation)
    - **SAVI**: Soil Adjusted Vegetation Index
    - **NDRE**: Normalized Difference Red Edge (chlorophyll)
    
    Plus overall health summary and recommendations.
    """
    boundary_geojson, farm = get_farm_boundary(farm_id, str(current_user.id), db)
    
    indices_service = get_indices_service(use_mock=True)
    
    results = await indices_service.process_all_indices(
        user_id=str(current_user.id),
        farm_id=farm_id,
        geojson_boundary=boundary_geojson
    )
    
    if results.get("status") == "NO_SATELLITE_DATA":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No satellite imagery available for this location"
        )
    
    return results


@router.get("/ndwi/{farm_id}", response_model=schemas.NDWIResponse)
async def get_ndwi(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Calculate NDWI (moisture index) for a farm.
    
    NDWI = (NIR - SWIR) / (NIR + SWIR)
    
    Interpretation:
    - **> 0.3**: High water content, well-irrigated
    - **0 to 0.3**: Moderate moisture
    - **< 0**: Water stress, needs irrigation
    """
    boundary_geojson, farm = get_farm_boundary(farm_id, str(current_user.id), db)
    
    indices_service = get_indices_service(use_mock=True)
    
    results = await indices_service.process_all_indices(
        user_id=str(current_user.id),
        farm_id=farm_id,
        geojson_boundary=boundary_geojson
    )
    
    ndwi_result = results["indices"]["NDWI"]
    
    recommendations = []
    if ndwi_result["mean"] is not None:
        if ndwi_result["mean"] < 0:
            recommendations.append("Water stress detected - consider immediate irrigation")
        elif ndwi_result["mean"] < 0.2:
            recommendations.append("Moderate moisture - monitor closely")
        else:
            recommendations.append("Good moisture levels")
    
    return {
        "farm_id": farm_id,
        "timestamp": datetime.now(),
        "ndwi": ndwi_result,
        "moisture_recommendations": recommendations
    }


@router.get("/evi/{farm_id}", response_model=schemas.EVIResponse)
async def get_evi(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Calculate EVI (Enhanced Vegetation Index) for a farm.
    
    Better than NDVI for dense vegetation and atmospheric interference.
    """
    boundary_geojson, farm = get_farm_boundary(farm_id, str(current_user.id), db)
    
    indices_service = get_indices_service(use_mock=True)
    
    results = await indices_service.process_all_indices(
        user_id=str(current_user.id),
        farm_id=farm_id,
        geojson_boundary=boundary_geojson
    )
    
    evi_result = results["indices"]["EVI"]
    
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
        "timestamp": datetime.now(),
        "evi": evi_result,
        "vegetation_analysis": analysis
    }


@router.get("/compare/{farm_id}")
async def compare_indices(
    farm_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Compare all indices side-by-side.
    """
    boundary_geojson, farm = get_farm_boundary(farm_id, str(current_user.id), db)
    
    indices_service = get_indices_service(use_mock=True)
    
    results = await indices_service.process_all_indices(
        user_id=str(current_user.id),
        farm_id=farm_id,
        geojson_boundary=boundary_geojson
    )
    
    return {
        "farm_id": farm_id,
        "farm_name": farm.name,
        "timestamp": datetime.now().isoformat(),
        "indices": results["indices"],
        "summary": results["summary"],
        "source": results["source"]
    }
