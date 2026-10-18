from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional, List, Literal

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
    client_id: Optional[str] = Field(None, max_length=50)

class RoundCreate(BaseModel):
    client_id: Optional[str] = Field(None, max_length=50)

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
    movement_points: float
    total_sessions_completed: int
    active_session: Optional[SessionResponse] = None


# ----------------------------------------------------
# COACH SCHEMAS
# ----------------------------------------------------
class ExerciseItem(BaseModel):
    name: str
    modality: Literal["weights", "calisthenics", "mobility", "yoga"]
    target_pattern: str  # e.g. "hip_hinge", "knee_flexion", "active_mobility"
    sets: int
    reps_or_duration: str  # e.g. "8 reps", "45s hold"
    rpe: Optional[int] = Field(None, ge=1, le=10)
    rest_seconds: Optional[int] = None
    transition_notes: Optional[str] = None
    notes: Optional[str] = None

class WorkoutBlock(BaseModel):
    block_name: Literal[
        "Prep / Dynamic Flow",
        "Primary Skill / Strength",
        "Accessory / Hypertrophy",
        "Down-Regulation / Cool Down",
    ]
    exercises: List[ExerciseItem]

# ExerciseItem, WorkoutBlock and CoachWorkoutResponse go to OpenAI strict parsing: no non-None defaults.
class CoachWorkoutResponse(BaseModel):
    flow_name: str
    estimated_total_minutes: int
    target_focus: str
    message: str
    diagnostic_needed: bool
    diagnostic_question: Optional[str] = None
    workout_summary: Optional[str] = None
    blocks: Optional[List[WorkoutBlock]] = None

class CoachChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    available_equipment: Optional[List[str]] = None
    target_duration_minutes: Optional[int] = Field(None, ge=5, le=240)
    context_overrides: Optional[dict] = None

class CreateFlowRequest(BaseModel):
    target_focus: str = Field(..., min_length=2, max_length=120)  # e.g. "hamstrings", "shoulder mobility"
    target_duration_minutes: int = Field(20, ge=5, le=120)
    available_equipment: Optional[List[str]] = None
    context_overrides: Optional[dict] = None

class FlowRecordResponse(BaseModel):
    id: int
    name: str
    target_focus: str
    duration_minutes: int
    routine_data: CoachWorkoutResponse
    created_at: str
