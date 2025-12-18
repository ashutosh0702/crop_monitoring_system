import json
import os
from typing import Generator
from src.config import settings

# --- JSON REPOSITORY (The "Mock" DB) ---
class JsonDatabase:
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

    # --- SIMULATE SQLALCHEMY METHODS ---
    # In future, these will be replaced by actual SQL queries
    
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
                updated_obj = field # Capture the full object
                break
        self.write(data)
        return updated_obj # Return the full dict including 'name', 'id', etc.

# Dependency Injection
def get_db() -> Generator:
    # FUTURE: yield SessionLocal()
    db = JsonDatabase()
    try:
        yield db
    finally:
        pass