import os
from pathlib import Path

class Settings:
    PROJECT_NAME: str = "Crop Monitoring System"
    PROJECT_VERSION: str = "1.0.0"
    
    # SECURITY
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # DATABASE (Switch this later for Docker/Postgres)
    # DATABASE_URL = "postgresql://user:pass@db:5432/agridb"
    DB_FILE: str = "local_db.json"
    
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    
    TIFF_STORAGE_PATH: Path = BASE_DIR / "data" / "ndvi_tifss"

settings = Settings()