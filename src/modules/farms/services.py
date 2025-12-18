import uuid
from src.database import JsonDatabase
from fastapi import HTTPException

class FarmService:
    def __init__(self, db: JsonDatabase):
        self.db = db

    def create_field(self, user_id: str, field_data):
        # 1. Enforce MVP Rule: Max 5 Fields
        existing_fields = self.db.get_fields_by_owner(user_id)
        if len(existing_fields) >= 5:
            raise HTTPException(
                status_code=400, 
                detail="Free Plan Limit: You cannot add more than 5 fields."
            )
        
        # 2. Create the base field object
        new_field = {
            "id": str(uuid.uuid4()),
            "owner_id": user_id,
            "name": field_data.name,
            "boundary": field_data.boundary.dict(),
            "area_acres": 2.5, # Placeholder for logic
            "latest_analysis": None,
            "analysis_history": []
        }
        # 3. Save
        return self.db.add_field(new_field)

    def get_my_fields(self, user_id: str):
        return self.db.get_fields_by_owner(user_id)
    
    def attach_analysis(self, field_id: str, analysis_results: dict):
        """Saves the NDVI results to the specific farm record"""
        return self.db.update_field_analysis(field_id, analysis_results)