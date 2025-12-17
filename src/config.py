import os

class Settings:
    PROJECT_NAME: str = "Kisan Crop Monitor"
    PROJECT_VERSION: str = "1.0.0"
    
    # SECURITY
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super-secret-key-change-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # DATABASE (Switch this later for Docker/Postgres)
    # DATABASE_URL = "postgresql://user:pass@db:5432/agridb"
    DB_FILE: str = "local_db.json"

settings = Settings()