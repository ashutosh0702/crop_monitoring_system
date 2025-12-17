# Crop Monitoring System

## Directory Structure

'''
crop_monitoring_system/
├── docker-compose.yml # Spins up API, Postgres/PostGIS, Redis
├── Dockerfile # Docker build instructions for API
├── requirements.txt # Python dependencies
├── .env # Secrets (DB URL, API Keys)
├── src/
│ ├── main.py # Entry point (FastAPI app init)
│ ├── config.py # Environment settings
│ ├── database.py # DB connection & Session management
│ │
│ ├── core/ # Universal utilities
│ │ ├── security.py # JWT Token handling
│ │ ├── exceptions.py # Custom error handling
│ │ └── utils.py # Geospatial helpers (WKT conversions)
│ │
│ ├── modules/ # DOMAIN LOGIC (The heart of the app)
│ │ ├── auth/ # User Login/Register
│ │ │ ├── router.py
│ │ │ ├── schemas.py
│ │ │ └── services.py
│ │ │
│ │ ├── farms/ # Geospatial Farm Management
│ │ │ ├── models.py # SQLAlchemy Models (with GeoAlchemy2)
│ │ │ ├── router.py # API Endpoints (Create Farm, Get Farms)
│ │ │ ├── schemas.py # Pydantic Models (Input/Output validation)
│ │ │ └── services.py # Business Logic (Area calc, Intersection check)
│ │ │
│ │ └── crops/ # Crop Data & ML Integration
│ │ ├── router.py
│ │ └── ml_engine.py # Interface to load/run TFLite/ONNX models
│ │
│ └── migrations/ # Alembic (DB Schema version control)

'''
