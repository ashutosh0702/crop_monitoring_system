from pydantic import BaseModel, Field

class UserBase(BaseModel):
    phone_number: str = Field(..., min_length=10, max_length=13)
    full_name: str

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: str
    is_active: bool
    
class Token(BaseModel):
    access_token: str
    token_type: str