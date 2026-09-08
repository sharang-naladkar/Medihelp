import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from .config import get_settings
from .database import SessionLocal
from .mission import generate_mission
from .models import Drone, Emergency, EmergencyStatus
from .mqtt_service import MQTTService
from .schemas import EmergencyCreate, EmergencyCreated, EmergencyRead
from .state import transition

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
settings = get_settings()

def get_db():
    with SessionLocal() as db: yield db

@asynccontextmanager
async def lifespan(app):
    service = MQTTService(settings)
    service.start()
    app.state.mqtt = service
    yield
    service.stop()

app = FastAPI(title="MediDrone Backend", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[str(settings.app_origin).rstrip("/")], allow_credentials=False, allow_methods=["GET","POST"], allow_headers=["content-type"])

@app.post("/api/v1/emergencies", response_model=EmergencyCreated, status_code=201)
def create_emergency(body: EmergencyCreate, request: Request, db: Session = Depends(get_db)):
    try:
        drone = db.scalar(select(Drone).where(Drone.status == "AVAILABLE").order_by((Drone.last_lat-body.lat)*(Drone.last_lat-body.lat)+(Drone.last_lng-body.lng)*(Drone.last_lng-body.lng)).limit(1))
        if drone is None: raise HTTPException(503, "No available drone")
        emergency = Emergency(**body.model_dump(), status=EmergencyStatus.RECEIVED)
        db.add(emergency); db.flush()
        emergency.drone_id = drone.id
        transition(emergency, EmergencyStatus.DRONE_ASSIGNED)
        mission = generate_mission(drone.last_lat, drone.last_lng, body.lat, body.lng)
        emergency.mission_json = {"items": mission}
        transition(emergency, EmergencyStatus.MISSION_GENERATED)
        db.commit(); db.refresh(emergency)
    except HTTPException: raise
    except SQLAlchemyError:
        db.rollback(); log.exception("Database failure while creating emergency")
        raise HTTPException(503, "Emergency service database unavailable")
    if not request.app.state.mqtt.publish_mission(emergency.id, mission):
        raise HTTPException(503, "Mission dispatch failed")
    try:
        transition(emergency, EmergencyStatus.DISPATCHED)
        db.merge(emergency); db.commit()
    except SQLAlchemyError:
        db.rollback(); log.exception("Database failure recording dispatch")
        raise HTTPException(503, "Mission sent but dispatch state could not be persisted")
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