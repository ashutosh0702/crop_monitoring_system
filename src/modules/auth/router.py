from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from src.database import get_db, JsonDatabase
from . import schemas, services

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=schemas.UserResponse)
def register(user: schemas.UserCreate, db: JsonDatabase = Depends(get_db)):
    auth_service = services.AuthService(db)
    new_user = auth_service.register_user(user)
    if not new_user:
        raise HTTPException(status_code=400, detail="Phone already registered")
    return new_user

@router.post("/token", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: JsonDatabase = Depends(get_db)):
    auth_service = services.AuthService(db)
    token = auth_service.login_user(form_data.username, form_data.password)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": token, "token_type": "bearer"}