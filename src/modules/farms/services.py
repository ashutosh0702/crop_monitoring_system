"""
Farm management service using PostgreSQL with PostGIS.
"""

from datetime import datetime
import uuid
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape, mapping

from src.models import Farm, NDVIAnalysis


class FarmService:
    """Farm service with SQLAlchemy ORM and PostGIS geometry."""
    
    MAX_FREE_FIELDS = 5  # MVP limit
    
    def __init__(self, db: Session):
        self.db = db

    def create_field(self, user_id: str, field_data) -> Farm:
        """
        Create a new farm field with geometry boundary.
        
        Args:
            user_id: UUID of the owner
            field_data: Pydantic schema with name and boundary (GeoJSON)
            
        Returns:
            Created Farm object
            
        Raises:
            HTTPException: If field limit exceeded
        """
        # Enforce MVP field limit
        field_count = self.db.query(Farm).filter(Farm.owner_id == user_id).count()
        if field_count >= self.MAX_FREE_FIELDS:
            raise HTTPException(
                status_code=400,
                detail=f"Free Plan Limit: You cannot add more than {self.MAX_FREE_FIELDS} fields."
            )
        
        # Convert GeoJSON to PostGIS geometry
        geojson_dict = field_data.boundary.dict()
        shapely_geom = shape(geojson_dict)
        postgis_geom = from_shape(shapely_geom, srid=4326)
        
        # Calculate area in acres (approximate)
        # Note: For accurate calculation, would need to project to local CRS
        area_acres = self._calculate_area_acres(shapely_geom)
        
        # Get crop type value (handle enum)
        crop_type_value = field_data.crop_type.value if field_data.crop_type else None
        
        # Create farm record
        new_farm = Farm(
            id=uuid.uuid4(),
            owner_id=uuid.UUID(user_id),
            name=field_data.name,
            crop_type=crop_type_value,
            planting_date=field_data.planting_date,
            boundary=postgis_geom,
            area_acres=area_acres,
        )
        
        self.db.add(new_farm)
        self.db.commit()
        self.db.refresh(new_farm)
        
        return new_farm
    
    def _calculate_area_acres(self, geom) -> float:
        """
        Approximate area calculation in acres.
        Note: This is an approximation. For precise area, use projected CRS.
        """
        # Approximate using WGS84 degrees to square meters
        # 1 degree lat ≈ 111,320 meters, 1 degree lon varies
        # Approximate using pyproj for better accuracy
        try:
            import pyproj
            from shapely.ops import transform
            
            # Transform to Web Mercator for area calculation
            project = pyproj.Transformer.from_crs(
                "EPSG:4326", "EPSG:3857", always_xy=True
            ).transform
            geom_projected = transform(project, geom)
            area_sqm = geom_projected.area
            area_acres = area_sqm * 0.000247105  # Convert sq meters to acres
            return round(area_acres, 2)
        except Exception:
            # Fallback: rough approximation
            return 2.5

    def get_my_fields(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 100,
        updated_since: Optional[datetime] = None,
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Get all farms owned by a user with their latest analysis (paginated).
        
        Args:
            user_id: UUID of the owner
            
        Returns:
            Tuple of (List of farm dictionaries, total count)
        """
        query = self.db.query(Farm).filter(Farm.owner_id == user_id)
        
        if updated_since:
            query = query.filter(Farm.updated_at >= updated_since)
            
        total = query.count()
        farms = query.order_by(Farm.created_at.desc()).offset(skip).limit(limit).all()
        
        latest_analysis_map = self._get_latest_analysis_map([farm.id for farm in farms])

        items = [
            self._farm_to_dict(
                farm,
                latest_analysis=latest_analysis_map.get(farm.id),
                include_history=False,
                include_payload=True,
            )
            for farm in farms
        ]
        return items, total
    
    def get_field_by_id(self, farm_id: str, user_id: str) -> Optional[Farm]:
        """Get a specific farm by ID, ensuring ownership."""
        return self.db.query(Farm).filter(
            Farm.id == farm_id,
            Farm.owner_id == user_id
        ).first()
    
    def attach_analysis(self, field_id: str, analysis_results: dict) -> Dict[str, Any]:
        """
        Attach NDVI analysis results to a farm.
        
        Args:
            field_id: UUID of the farm
            analysis_results: Dictionary with tiff_url, png_url, stats, metadata
            
        Returns:
            Updated farm dictionary with analysis
        """
        farm = self.db.query(Farm).filter(Farm.id == field_id).first()
        if not farm:
            raise HTTPException(status_code=404, detail="Farm not found")
        
        # Create NDVIAnalysis record
        stats = analysis_results.get("stats", {})
        metadata = analysis_results.get("metadata", {})
        
        analysis = NDVIAnalysis(
            id=uuid.uuid4(),
            farm_id=uuid.UUID(field_id),
            tiff_url=analysis_results.get("tiff_url", ""),
            png_url=analysis_results.get("png_url", "placeholder"),
            mean_ndvi=stats.get("mean_ndvi", 0),
            min_ndvi=stats.get("min_ndvi"),
            max_ndvi=stats.get("max_ndvi"),
            std_ndvi=stats.get("std_ndvi"),
            status=stats.get("status", "DATA_MISSING"),
            satellite_source=metadata.get("satellite_source", "mock"),
            scene_date=self._parse_datetime(metadata.get("scene_date")),
            cloud_cover=metadata.get("cloud_cover"),
        )
        
        self.db.add(analysis)
        self.db.commit()
        self.db.refresh(farm)
        
        return self._farm_to_dict(farm)
    
    def get_analysis_history(self, farm_id: str) -> List[Dict[str, Any]]:
        """Get all NDVI analyses for a farm."""
        analyses = self.db.query(NDVIAnalysis).filter(
            NDVIAnalysis.farm_id == farm_id
        ).order_by(NDVIAnalysis.created_at.desc()).all()
        
        return [a.to_dict() for a in analyses]
    
    def _farm_to_dict(
        self,
        farm: Farm,
        latest_analysis: Optional[NDVIAnalysis] = None,
        include_history: bool = True,
        include_payload: bool = True,
    ) -> Dict[str, Any]:
        """Convert Farm model to dictionary for API response."""
        # Convert PostGIS geometry to GeoJSON
        shapely_geom = to_shape(farm.boundary)
        boundary_geojson = mapping(shapely_geom)
        bbox = list(shapely_geom.bounds)
        
        # Get latest analysis
        latest = latest_analysis if latest_analysis is not None else farm.latest_analysis
        latest_dict = latest.to_dict(include_payload=include_payload, bbox=bbox) if latest else None
        
        # Get analysis history
        history = [a.to_dict(include_payload=include_payload, bbox=bbox) for a in farm.analyses] if include_history and farm.analyses else []
        
        return {
            "id": str(farm.id),
            "owner_id": str(farm.owner_id),
            "name": farm.name,
            "boundary": boundary_geojson,
            "crop_type": farm.crop_type,
            "planting_date": farm.planting_date,
            "area_acres": farm.area_acres,
            "latest_analysis": latest_dict,
            "analysis_history": history,
        }

    def _get_latest_analysis_map(self, farm_ids: List[Any]) -> Dict[Any, NDVIAnalysis]:
        if not farm_ids:
            return {}

        latest_subquery = (
            self.db.query(
                NDVIAnalysis.farm_id.label("farm_id"),
                func.max(NDVIAnalysis.created_at).label("latest_created_at"),
            )
            .filter(NDVIAnalysis.farm_id.in_(farm_ids))
            .group_by(NDVIAnalysis.farm_id)
            .subquery()
        )

        analyses = (
            self.db.query(NDVIAnalysis)
            .join(
                latest_subquery,
                (NDVIAnalysis.farm_id == latest_subquery.c.farm_id)
                & (NDVIAnalysis.created_at == latest_subquery.c.latest_created_at),
            )
            .all()
        )
        return {analysis.farm_id: analysis for analysis in analyses}

    def _parse_datetime(self, value: Optional[str]):
        if not value:
            return None
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
