import logging
import os
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from .config import DatabaseSettings
from .database import SessionLocal
from .models import Emergency, EmergencyStatus
from .schemas import EmergencyCreate, EmergencyCreated, EmergencyRead

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
database_settings = DatabaseSettings()

def get_db():
    with SessionLocal() as db: yield db

app = FastAPI(title="MediDrone Backend")
app_origin = os.getenv("APP_ORIGIN", "").rstrip("/")
app.add_middleware(CORSMiddleware, allow_origins=[app_origin] if app_origin else [], allow_credentials=False, allow_methods=["GET","POST"], allow_headers=["content-type"])

@app.post("/api/v1/emergencies", response_model=EmergencyCreated, status_code=201)
def create_emergency(body: EmergencyCreate, db: Session = Depends(get_db)):
    """Step 2: persist an emergency only; dispatch is added in later steps."""
    emergency = Emergency(**body.model_dump(), status=EmergencyStatus.RECEIVED)
    try:
        db.add(emergency); db.commit(); db.refresh(emergency)
    except SQLAlchemyError:
        db.rollback(); log.exception("Database failure while creating emergency")
        raise HTTPException(503, "Emergency service database unavailable")
    return EmergencyCreated(emergency_id=emergency.id)

@app.get("/api/v1/emergencies/{emergency_id}", response_model=EmergencyRead)
def get_emergency(emergency_id: str, db: Session = Depends(get_db)):
    try: emergency = db.get(Emergency, emergency_id)
    except (SQLAlchemyError, ValueError):
        log.exception("Database failure retrieving emergency")
        raise HTTPException(503, "Emergency service database unavailable")
    if emergency is None: raise HTTPException(404, "Emergency not found")
    telemetry = emergency.telemetry or {}
    return EmergencyRead(status=emergency.status, drone_lat=telemetry.get("lat"), drone_lng=telemetry.get("lng"), battery_pct=telemetry.get("battery_pct"), eta_seconds=None)