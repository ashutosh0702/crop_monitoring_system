import os
from pathlib import Path
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Project Info
    PROJECT_NAME: str = "Crop Monitoring System"
    PROJECT_VERSION: str = "2.0.0"
    
    # Security
    SECRET_KEY: str = "super-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    # Database (PostgreSQL with PostGIS)
    DATABASE_URL: str = "postgresql://user:pass@db:5432/crop_monitoring"
    
    # Redis (Celery broker)
    REDIS_URL: str = "redis://redis:6379/0"
    
    # AWS S3 Configuration
    AWS_ACCESS_KEY_ID: str = "placeholder"
    AWS_SECRET_ACCESS_KEY: str = "placeholder"
    AWS_S3_BUCKET: str = "crop-monitoring-tiffs"
    AWS_REGION: str = "ap-south-1"
    
    # External APIs
    OPENWEATHERMAP_API_KEY: str = "placeholder"
    
    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    TIFF_STORAGE_PATH: Path = BASE_DIR / "data" / "ndvi_tiffs"
    PNG_STORAGE_PATH: Path = BASE_DIR / "data" / "false_color"
    
    # Legacy - for backward compatibility during migration
    DB_FILE: str = "local_db.json"
    
    # Environment mode
    ENVIRONMENT: str = "development"  # development, staging, production
    
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"
    
    @property
    def use_s3(self) -> bool:
        """Use S3 for storage in production, local filesystem in development."""
        return self.is_production and self.AWS_ACCESS_KEY_ID != "placeholder"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance for dependency injection."""
    return Settings()


# Global settings instance (for backward compatibility)
settings = get_settings()