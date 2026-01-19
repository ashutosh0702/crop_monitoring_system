"""
Authentication service using PostgreSQL database.
"""

import uuid
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException

from src.core.security import get_password_hash, verify_password, create_access_token
from src.models import User


class AuthService:
    """Authentication service with SQLAlchemy ORM."""
    
    def __init__(self, db: Session):
        self.db = db

    def register_user(self, user_data) -> Optional[User]:
        """
        Register a new user.
        
        Args:
            user_data: Pydantic schema with phone_number, full_name, password
            
        Returns:
            User object if created, None if user already exists
        """
        # Check if user already exists
        existing = self.db.query(User).filter(
            User.phone_number == user_data.phone_number
        ).first()
        
        if existing:
            return None  # User already exists
        
        # Create new user
        new_user = User(
            id=uuid.uuid4(),
            phone_number=user_data.phone_number,
            full_name=user_data.full_name,
            hashed_password=get_password_hash(user_data.password),
            is_active=True,
        )
        
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        
        return new_user

    def login_user(self, phone: str, password: str) -> Optional[str]:
        """
        Authenticate user and return JWT token.
        
        Args:
            phone: User's phone number
            password: Plain text password
            
        Returns:
            JWT token string if authenticated, None otherwise
        """
        user = self.db.query(User).filter(User.phone_number == phone).first()
        
        if not user or not verify_password(password, user.hashed_password):
            return None
        
        token = create_access_token(data={"sub": user.phone_number})
        return token
    
    def get_user_by_phone(self, phone: str) -> Optional[User]:
        """Get user by phone number."""
        return self.db.query(User).filter(User.phone_number == phone).first()
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by UUID."""
        return self.db.query(User).filter(User.id == user_id).first()