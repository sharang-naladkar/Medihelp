import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class EmergencyStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    DRONE_ASSIGNED = "DRONE_ASSIGNED"
    MISSION_GENERATED = "MISSION_GENERATED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    APPROACHING = "APPROACHING"
    ARRIVED = "ARRIVED"
    AED_DELIVERED = "AED_DELIVERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Drone(Base):
    __tablename__ = "drones"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    callsign: Mapped[str] = mapped_column(String(128), nullable=False)
    last_lat: Mapped[float] = mapped_column(Float, nullable=False)
    last_lng: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="AVAILABLE")
    battery_pct: Mapped[float | None] = mapped_column(Float)

class Emergency(Base):
    __tablename__ = "emergencies"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    aadhaar_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[EmergencyStatus] = mapped_column(Enum(EmergencyStatus, name="emergency_status"), nullable=False)
    drone_id: Mapped[str | None] = mapped_column(ForeignKey("drones.id"))
    mission_json: Mapped[dict | None] = mapped_column(JSONB)
    telemetry: Mapped[dict | None] = mapped_column(JSONB)
    rescue_report: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)