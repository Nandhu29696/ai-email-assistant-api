from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    # Tokens are delivered as httpOnly cookies; they appear in the body only
    # for API clients that send "X-Auth-Mode: token".
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    role: str
    username: str
    full_name: Optional[str] = None
    user_id: int
    mfa_enabled: Optional[bool] = None
    # Set when a second factor is required: POST /api/auth/mfa/verify
    mfa_required: Optional[bool] = None
    mfa_token: Optional[str] = None


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str]
    role: str
    is_active: bool
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    mfa_enabled: bool = False
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
