import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from .models import EmergencyStatus

class EmergencyCreate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0)
    timestamp: datetime
    name: str = Field(min_length=1, max_length=256)
    phone: str = Field(min_length=3, max_length=64)
    aadhaar_last4: str = Field(pattern=r"^\d{4}$")

class EmergencyCreated(BaseModel):
    emergency_id: uuid.UUID

class EmergencyRead(BaseModel):
    status: EmergencyStatus
    drone_lat: float | None
    drone_lng: float | None
    battery_pct: float | None
    eta_seconds: int | None