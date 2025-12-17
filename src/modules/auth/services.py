import uuid
from src.core.security import get_password_hash, verify_password, create_access_token
from src.database import JsonDatabase

class AuthService:
    def __init__(self, db: JsonDatabase):
        self.db = db

    def register_user(self, user_data):
        # 1. Check if exists
        if self.db.get_user_by_phone(user_data.phone_number):
            return None # User exists
        
        # 2. Hash Password
        user_dict = user_data.dict()
        user_dict["hashed_password"] = get_password_hash(user_dict.pop("password"))
        user_dict["id"] = str(uuid.uuid4())
        user_dict["is_active"] = True
        
        # 3. Save
        return self.db.add_user(user_dict)

    def login_user(self, phone, password):
        user = self.db.get_user_by_phone(phone)
        if not user or not verify_password(password, user["hashed_password"]):
            return None
        
        token = create_access_token(data={"sub": user["phone_number"]})
        return token