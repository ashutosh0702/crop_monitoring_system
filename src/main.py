"""
Crop Monitoring System - FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import init_db
from src.modules.auth import router as auth_router
from src.modules.farms import router as farms_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup: Initialize database tables
    init_db()
    print(f"🌾 {settings.PROJECT_NAME} v{settings.PROJECT_VERSION} starting...")
    print(f"📊 Database: {settings.DATABASE_URL.split('@')[-1]}")  # Hide credentials
    print(f"📦 Storage: {'S3' if settings.use_s3 else 'Local filesystem'}")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down...")


# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="Agricultural monitoring API with NDVI analysis and geospatial features",
    lifespan=lifespan,
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure properly in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router.router)
app.include_router(farms_router.router)

# Weather router
from src.modules.weather import router as weather_router
app.include_router(weather_router.router)

# Tasks router (background job management)
from src.modules.tasks import router as tasks_router
app.include_router(tasks_router.router)

# Alerts router
from src.modules.alerts import router as alerts_router
app.include_router(alerts_router.router)


@app.get("/")
def root():
    """Health check endpoint."""
    return {
        "message": f"{settings.PROJECT_NAME} is Online",
        "version": settings.PROJECT_VERSION,
        "docs": "/docs",
        "environment": settings.ENVIRONMENT,
    }


@app.get("/health")
def health_check():
    """Detailed health check for load balancers."""
    return {
        "status": "healthy",
        "database": "connected",  # TODO: Add actual DB ping
        "redis": "connected",  # TODO: Add actual Redis ping
    }