from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional, List

# ----------------------------------------------------
# USER SCHEMAS
# ----------------------------------------------------
class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=80)
    email: EmailStr

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    created_at: datetime

    class Config:
        from_attributes = True


# ----------------------------------------------------
# WORKOUT & SET SCHEMAS
# ----------------------------------------------------
class SessionCreate(BaseModel):
    user_id: int

class SetCreate(BaseModel):
    reps: int = Field(..., gt=0, le=150)  # Must be greater than 0, reasonable cap
    client_id: Optional[str] = Field(None, max_length=36)

class SetResponse(BaseModel):
    id: int
    session_id: int
    reps: int
    created_at: datetime

    class Config:
        from_attributes = True

class SessionResponse(BaseModel):
    id: int
    user_id: int
    target_pushups: int
    is_completed: bool
    created_at: datetime
    sets: List[SetResponse] = []

    class Config:
        from_attributes = True


# ----------------------------------------------------
# STATISTICS / DASHBOARD SCHEMAS
# ----------------------------------------------------
class UserStatsResponse(BaseModel):
    user_id: int
    cumulative_pushups: int
    total_sessions_completed: int
    active_session: Optional[SessionResponse] = None
