import logging, os
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from .config import MissionSettings
from .database import SessionLocal
from .mission import generate_mission
from .models import Drone, Emergency, EmergencyStatus
from .mqtt_service import MQTTService
from .schemas import EmergencyCreate, EmergencyCreated, EmergencyRead
from .state import transition

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
settings = MissionSettings()

def get_db():
    db = None
    try:
        db = SessionLocal()
        yield db
    except SQLAlchemyError:
        if db is not None:
            db.rollback()
        log.exception("Database connection or session failure")
        raise HTTPException(503, "Emergency service database unavailable")
    finally:
        if db is not None:
            db.close()

@asynccontextmanager
async def lifespan(app):
    service = MQTTService(settings)
    service.start(subscribe=True)
    app.state.mqtt = service
    yield
    service.stop()

app = FastAPI(title="MediDrone Backend", lifespan=lifespan)
app_origin = os.getenv("APP_ORIGIN", "").rstrip("/")
app.add_middleware(CORSMiddleware, allow_origins=[app_origin] if app_origin else [], allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["content-type"])

@app.post("/api/v1/emergencies", response_model=EmergencyCreated, status_code=201)
def create_emergency(body: EmergencyCreate, db: Session = Depends(get_db)):
    try:
        drone = db.scalar(select(Drone).where(Drone.id == settings.drone_id, Drone.status == "AVAILABLE").with_for_update())
        if drone is None:
            raise HTTPException(503, "No available drone")
        emergency = Emergency(**body.model_dump(), status=EmergencyStatus.RECEIVED, drone_id=drone.id)
        db.add(emergency)
        db.flush()
        transition(emergency, EmergencyStatus.DRONE_ASSIGNED)
        mission = generate_mission(drone.last_lat, drone.last_lng, body.lat, body.lng)
        emergency.mission_json = {"items": mission}
        transition(emergency, EmergencyStatus.MISSION_GENERATED)
        db.commit()
        db.refresh(emergency)
    except HTTPException:
        raise
    except SQLAlchemyError:
        db.rollback()
        log.exception("Database failure while generating mission")
        raise HTTPException(503, "Emergency service database unavailable")
    if not app.state.mqtt.publish_mission(emergency.id, mission):
        raise HTTPException(503, "Mission dispatch failed")
    try:
        transition(emergency, EmergencyStatus.DISPATCHED)
        db.merge(emergency)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        log.exception("Database failure recording dispatch")
        raise HTTPException(503, "Mission sent but dispatch state could not be persisted")
    return EmergencyCreated(emergency_id=emergency.id)

@app.get("/api/v1/emergencies/{emergency_id}", response_model=EmergencyRead)
def get_emergency(emergency_id: str, db: Session = Depends(get_db)):
    try:
        emergency = db.get(Emergency, emergency_id)
    except (SQLAlchemyError, ValueError):
        log.exception("Database failure retrieving emergency")
        raise HTTPException(503, "Emergency service database unavailable")
    if emergency is None:
        raise HTTPException(404, "Emergency not found")
    telemetry = emergency.telemetry or {}
    return EmergencyRead(status=emergency.status, drone_lat=telemetry.get("lat"), drone_lng=telemetry.get("lng"), battery_pct=telemetry.get("battery_pct"), eta_seconds=None)
