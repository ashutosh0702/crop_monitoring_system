from fastapi import APIRouter, Depends
from src.database import get_db, JsonDatabase
from src.core import security
from fastapi.security import OAuth2PasswordBearer
from . import schemas, services

router = APIRouter(prefix="/fields", tags=["Farms"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# --- Dependency to get Current User ID from Token ---
def get_current_user_id(token: str = Depends(oauth2_scheme), db: JsonDatabase = Depends(get_db)):
    payload = security.jwt.decode(token, security.settings.SECRET_KEY, algorithms=[security.settings.ALGORITHM])
    phone = payload.get("sub")
    user = db.get_user_by_phone(phone)
    return user["id"]

@router.post("/", response_model=schemas.FieldResponse)
def add_field(
    field: schemas.FieldCreate, 
    user_id: str = Depends(get_current_user_id),
    db: JsonDatabase = Depends(get_db)
):
    farm_service = services.FarmService(db)
    return farm_service.create_field(user_id, field)

@router.get("/", response_model=list[schemas.FieldResponse])
def get_fields(
    user_id: str = Depends(get_current_user_id),
    db: JsonDatabase = Depends(get_db)
):
    farm_service = services.FarmService(db)
    return farm_service.get_my_fields(user_id)