"""
Authentication router with PostgreSQL database.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from src.database import get_db
from . import schemas, services

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=schemas.UserResponse)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user account.
    
    - **phone_number**: Unique phone number (used as username)
    - **full_name**: User's display name
    - **password**: Password (will be hashed)
    """
    auth_service = services.AuthService(db)
    new_user = auth_service.register_user(user)
    
    if not new_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number already registered"
        )
    
    return {
        "id": str(new_user.id),
        "phone_number": new_user.phone_number,
        "full_name": new_user.full_name,
        "is_active": new_user.is_active,
    }


@router.post("/token", response_model=schemas.Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login and obtain an access token.
    
    - **username**: Phone number
    - **password**: Password
    """
    auth_service = services.AuthService(db)
    token = auth_service.login_user(form_data.username, form_data.password)
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return {"access_token": token, "token_type": "bearer"}