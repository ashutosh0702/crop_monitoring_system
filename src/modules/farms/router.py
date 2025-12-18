from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from src.database import get_db, JsonDatabase
from src.core import security
from fastapi.security import OAuth2PasswordBearer
from . import schemas, services
from fastapi.responses import FileResponse
from src.modules.crops.ndvi_service import NDVILogic
import os
from typing import List



router = APIRouter(prefix="/fields", tags=["Farms"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

ndvi_engine = NDVILogic()

# --- Dependency to get Current User ID from Token ---
def get_current_user_id(token: str = Depends(oauth2_scheme), db: JsonDatabase = Depends(get_db)):
    payload = security.jwt.decode(token, security.settings.SECRET_KEY, algorithms=[security.settings.ALGORITHM])
    phone = payload.get("sub")
    user = db.get_user_by_phone(phone)
    return user["id"]

@router.post("/", response_model=schemas.FieldResponse)
async def add_field_and_analyze(
    field: schemas.FieldCreate, 
    user_id: str = Depends(get_current_user_id),
    db: JsonDatabase = Depends(get_db)
):
    farm_service = services.FarmService(db)
    new_field_record =  farm_service.create_field(user_id, field)
    farm_id = new_field_record["id"]
    # 2. Trigger NDVI Analysis
    # We pass the boundary (GeoJSON) to the engine
    analysis_results = await ndvi_engine.process_field_ndvi(
        user_id=user_id,
        farm_id=farm_id,
        geojson_boundary=field.boundary.dict())
    
    # 3. PERMANENTLY STORE results in the DB linked to this field
    updated_analysis = farm_service.attach_analysis(
        field_id=farm_id, 
        analysis_results=analysis_results
    )
    
    # 4. Return the combined data to the frontend
    #new_field_record["latest_analysis"] = updated_analysis
    
    return updated_analysis

@router.get("/", response_model=list[schemas.FieldResponse])
def get_fields(
    user_id: str = Depends(get_current_user_id),
    db: JsonDatabase = Depends(get_db)
):
    farm_service = services.FarmService(db)
    return farm_service.get_my_fields(user_id)


@router.get("/{farm_id}/history", response_model=List[schemas.NDVIAnalysis])
async def get_farm_history(
    farm_id: str,
    user_id: str = Depends(get_current_user_id),
    db: JsonDatabase = Depends(get_db)
):
    """
    Returns the full timeline of NDVI scans for a specific farm.
    Used for plotting the 'Health Trend' chart.
    """
    farm_service = services.FarmService(db)
    
    # Fetch all fields for this user
    fields = farm_service.get_my_fields(user_id)
    
    # Find the specific farm
    target_farm = next((f for f in fields if f["id"] == farm_id), None)
    
    if not target_farm:
        raise HTTPException(status_code=404, detail="Farm not found")
        
    # Return the history list (or empty list if never scanned)
    return target_farm.get("analysis_history", [])