from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None   # included on login; omitted on API calls
    token_type: str = "bearer"
    role: str
    username: str
    full_name: Optional[str] = None
    user_id: int


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
