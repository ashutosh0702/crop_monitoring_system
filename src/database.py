"""
Database connection and session management.
Supports both PostgreSQL/PostGIS (production) and legacy JSON database (migration).
"""

import json
import os
from typing import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from src.config import settings
from src.models import Base


# =============================================================================
# PostgreSQL Database Engine (Primary)
# =============================================================================

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connection before using
    poolclass=QueuePool,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    Initialize database connection check.
    
    NOTE: We use Alembic for schema management, not create_all().
    Run: docker compose exec api alembic upgrade head
    
    This function just verifies the database connection.
    """
    from sqlalchemy import text
    try:
        # Verify connection works
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("✅ Database connection verified")
    except Exception as e:
        print(f"⚠️ Database connection failed: {e}")
        # Don't raise - allow app to start for debugging


def get_db() -> Generator[Session, None, None]:
    """
    Dependency injection for database sessions.
    Usage in FastAPI:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions (non-FastAPI usage)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# =============================================================================
# Legacy JSON Database (For Migration Period)
# =============================================================================

class JsonDatabase:
    """
    Legacy JSON-based database for backward compatibility during migration.
    Will be removed after full PostgreSQL migration.
    """
    def __init__(self):
        self.file_path = settings.DB_FILE
        self._ensure_db_exists()

    def _ensure_db_exists(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w") as f:
                json.dump({"users": [], "fields": []}, f)

    def read(self):
        with open(self.file_path, "r") as f:
            return json.load(f)

    def write(self, data):
        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=4)

    def get_user_by_phone(self, phone: str):
        data = self.read()
        for user in data["users"]:
            if user["phone_number"] == phone:
                return user
        return None

    def add_user(self, user_data: dict):
        data = self.read()
        data["users"].append(user_data)
        self.write(data)
        return user_data

    def get_fields_by_owner(self, owner_id: str):
        data = self.read()
        return [f for f in data["fields"] if f["owner_id"] == owner_id]

    def add_field(self, field_data: dict):
        data = self.read()
        data["fields"].append(field_data)
        self.write(data)
        return field_data
    
    def update_field_analysis(self, field_id: str, analysis_data: dict):
        data = self.read()
        updated_obj = None
        for field in data["fields"]:
            if field["id"] == field_id:
                field["latest_analysis"] = analysis_data
                if "analysis_history" not in field:
                    field["analysis_history"] = []
                field["analysis_history"].append(analysis_data)
                updated_obj = field
                break
        self.write(data)
        return updated_obj


def get_json_db() -> Generator:
    """
    Legacy dependency for JSON database.
    Replace with get_db() after migration.
    """
    db = JsonDatabase()
    try:
        yield db
    finally:
        pass