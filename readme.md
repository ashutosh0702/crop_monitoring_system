# 🌾 Crop Monitoring System

> Agricultural monitoring API with NDVI analysis, geospatial features, and satellite imagery integration.

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blue.svg)](https://www.postgresql.org/)
[![PostGIS](https://img.shields.io/badge/PostGIS-3.3+-orange.svg)](https://postgis.net/)

---

## 📖 Overview

A comprehensive agricultural monitoring platform that enables farmers to:
- **Register farm boundaries** using GeoJSON polygons
- **Analyze crop health** via NDVI (Normalized Difference Vegetation Index)
- **Track vegetation trends** over time with historical analysis
- **Receive alerts** when crop health drops below thresholds

### Key Features

| Feature | Description |
|---------|-------------|
| 🗺️ **Geospatial Storage** | Farm boundaries stored as PostGIS geometry |
| 🛰️ **Satellite Imagery** | Free Sentinel-2 data via STAC API (Element84) |
| 📊 **NDVI Analysis** | Real-time vegetation health classification |
| 🖼️ **False Color Composites** | Visual PNG outputs alongside GeoTIFFs |
| ⚡ **Background Processing** | Celery + Redis for async task handling |
| 🔐 **JWT Authentication** | Secure user registration and login |

---

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   FastAPI App   │────▶│  PostgreSQL     │     │     Redis       │
│   (Port 8000)   │     │  + PostGIS      │     │   (Port 6379)   │
└────────┬────────┘     └─────────────────┘     └────────┬────────┘
         │                                               │
         │              ┌─────────────────┐              │
         └─────────────▶│  Celery Worker  │◀─────────────┘
                        │  (Background)   │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │   STAC API      │
                        │  (Sentinel-2)   │
                        └─────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- [Docker](https://www.docker.com/products/docker-desktop/) (with Docker Compose)
- Git

### 1. Clone & Configure

```bash
git clone <repository-url>
cd crop_monitoring_system

# Copy environment template
cp .env.example .env
```

### 2. Start Services

```bash
# Build and start all containers
docker compose up -d --build

# Run database migrations
docker compose exec api alembic upgrade head
```

### 3. Access the API

| Service | URL |
|---------|-----|
| 🌐 **API** | http://localhost:8000 |
| 📚 **Swagger Docs** | http://localhost:8000/docs |
| 🔍 **ReDoc** | http://localhost:8000/redoc |

---

## 📁 Project Structure

```
crop_monitoring_system/
├── docker-compose.yml      # Container orchestration
├── Dockerfile              # Multi-stage Python build
├── requirements.txt        # Python dependencies
├── alembic.ini             # Database migration config
├── .env.example            # Environment template
│
├── alembic/                # Database migrations
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── src/
│   ├── main.py             # FastAPI app entry point
│   ├── config.py           # Environment settings (pydantic)
│   ├── database.py         # SQLAlchemy connection
│   ├── models.py           # Database models (GeoAlchemy2)
│   ├── celery_app.py       # Celery configuration
│   ├── tasks.py            # Background task definitions
│   │
│   ├── core/               # Shared utilities
│   │   ├── security.py     # JWT token handling
│   │   ├── exceptions.py   # Custom errors
│   │   └── utils.py        # Geospatial helpers
│   │
│   └── modules/            # Domain logic
│       ├── auth/           # User authentication
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── services.py
│       │
│       ├── farms/          # Farm management
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── services.py
│       │
│       └── crops/          # NDVI & Satellite
│           ├── ndvi_service.py
│           └── stac_client.py
│
└── data/                   # Generated outputs
    ├── ndvi_tiffs/         # GeoTIFF files
    └── false_color/        # PNG composites
```

---

## 🔌 API Endpoints

### Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/auth/register` | Register new user (phone + password) |
| `POST` | `/auth/token` | Login and get JWT token |

### Farms

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/fields/` | List all user's farms |
| `POST` | `/fields/` | Create farm + trigger NDVI analysis |
| `GET` | `/fields/{farm_id}/history` | Get NDVI history timeline |

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | API status message |
| `GET` | `/health` | Detailed health check |

---

## ⚙️ Configuration

Environment variables (`.env`):

```env
# Database
DATABASE_URL=postgresql://user:pass@db:5432/crop_monitoring

# Redis (Celery broker)
REDIS_URL=redis://redis:6379/0

# Security
SECRET_KEY=your-super-secret-key

# AWS S3 (optional - for production)
AWS_ACCESS_KEY_ID=placeholder
AWS_SECRET_ACCESS_KEY=placeholder
AWS_S3_BUCKET=crop-monitoring-tiffs
AWS_REGION=ap-south-1

# External APIs
OPENWEATHERMAP_API_KEY=placeholder
```

---

## 🛠️ Development

### Local Development (without Docker)

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Start PostgreSQL and Redis (requires local installation)
# Then run:
uvicorn src.main:app --reload
```

### Running Tests

```bash
# Inside Docker
docker compose exec api pytest tests/ -v

# Locally
pytest tests/ -v
```

### Database Migrations

```bash
# Create new migration
docker compose exec api alembic revision --autogenerate -m "description"

# Apply migrations
docker compose exec api alembic upgrade head

# Rollback
docker compose exec api alembic downgrade -1
```

---

## 🛰️ Satellite Data

This system uses **free Sentinel-2 imagery** via the [STAC API](https://stacspec.org/):

- **Provider**: Element84 Earth Search
- **Collection**: `sentinel-2-l2a` (Level-2A surface reflectance)
- **Bands Used**: 
  - B04 (Red) - 10m resolution
  - B08 (NIR) - 10m resolution
  - B03 (Green) - for false color composites

### Mock Mode

For local development without internet access, the system falls back to mock data:

```python
# In ndvi_service.py
ndvi_engine = NDVILogic(use_mock=True)  # Uses random synthetic data
```

---

## 📊 NDVI Classification

| NDVI Range | Status | Description |
|------------|--------|-------------|
| ≥ 0.50 | 🟢 HEALTHY | Dense, healthy vegetation |
| 0.25 - 0.49 | 🟡 MODERATE | Sparse vegetation or stress |
| < 0.25 | 🔴 CRITICAL | Bare soil, water, or dead plants |

---

## 🐳 Docker Commands

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f api
docker compose logs -f celery_worker

# Stop services
docker compose down

# Reset database (delete volumes)
docker compose down -v

# Rebuild after code changes
docker compose up -d --build

# Access PostgreSQL
docker compose exec db psql -U user -d crop_monitoring
```

---

## 🗺️ Roadmap

### ✅ Phase 0: Infrastructure (Complete)
- [x] PostgreSQL + PostGIS database
- [x] Celery + Redis task queue
- [x] Docker Compose orchestration
- [x] Alembic migrations

### ✅ Phase 1: Satellite Integration (Complete)
- [x] STAC API client for Sentinel-2
- [x] Rasterio COG streaming
- [x] NDVI calculation
- [x] False color PNG composites

### 🔄 Phase 2: Advanced Indices (Planned)
- [ ] NDWI (Water Index)
- [ ] EVI (Enhanced Vegetation Index)
- [ ] Soil data integration

### 📋 Phase 3: Monitoring (Planned)
- [ ] Automated scan scheduling
- [ ] Alert notifications
- [ ] Weather integration

### ☁️ AWS Deployment (Planned)
- [ ] Lambda + API Gateway
- [ ] RDS PostgreSQL
- [ ] S3 for file storage

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request
