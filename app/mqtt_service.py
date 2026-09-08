import json, logging, threading, time, uuid
from datetime import datetime, timezone
from urllib.parse import unquote, urlparse
import httpx
import paho.mqtt.client as mqtt
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from .database import SessionLocal
from .models import Emergency, EmergencyStatus
from .state import transition

log = logging.getLogger(__name__)

class MQTTService:
    def __init__(self, settings):
        self.settings = settings
        parsed = urlparse(str(settings.mqtt_broker_url))
        if parsed.scheme not in {"mqtt", "mqtts"} or not parsed.hostname:
            raise ValueError("MQTT_BROKER_URL must be mqtt:// or mqtts:// with a host")
        self.host = parsed.hostname
        self.port = parsed.port or (8883 if parsed.scheme == "mqtts" else 1883)
        self.username = unquote(parsed.username) if parsed.username else None
        self.password = unquote(parsed.password or "") if parsed.username else ""
        self.tls_enabled = parsed.scheme == "mqtts"
        self.client_id = f"medidrone-backend-{settings.drone_id}"
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, protocol=mqtt.MQTTv311, clean_session=True)
        if self.username is not None:
            self.client.username_pw_set(self.username, self.password)
        if self.tls_enabled:
            self.client.tls_set()
        self.client.on_connect, self.client.on_message = self._on_connect, self._on_message

    def start(self, *, subscribe=True):
        self.subscribe_enabled = subscribe
        if not self.settings.mqtt_enabled:
            log.warning("MQTT disabled via feature flag — skipping real publish, using fallback simulation")
            return
        username_bytes = len(self.username.encode("utf-8")) if self.username is not None else 0
        password_bytes = len(self.password.encode("utf-8"))
        log.info("MQTT connecting host=%s port=%s username=%s username_bytes=%s password_bytes=%s client_id=%s protocol=MQTTv311 tls=%s", self.host, self.port, self.username or "<none>", username_bytes, password_bytes, self.client_id, self.tls_enabled)
        self.client.connect(self.host, self.port, 60)
        self.client.loop_start()

    def stop(self):
        if self.settings.mqtt_enabled:
            self.client.loop_stop()
            self.client.disconnect()

    def publish_mission(self, emergency_id, items):
        if not self.settings.mqtt_enabled:
            log.warning("MQTT disabled via feature flag — skipping real publish, using fallback simulation")
            threading.Thread(target=self._simulate_emergency, args=(emergency_id,), name=f"demo-emergency-{emergency_id}", daemon=True).start()
            return True
        topic = f"drone/{self.settings.drone_id}/mission"
        payload = json.dumps({"emergency_id": str(emergency_id), "mission": items})
        for attempt in range(1, self.settings.mqtt_publish_retries + 1):
            try:
                info = self.client.publish(topic, payload, qos=1)
                info.wait_for_publish(timeout=5)
                published, rc = info.rc == mqtt.MQTT_ERR_SUCCESS and info.is_published(), info.rc
            except (RuntimeError, OSError) as exc:
                published, rc = False, str(exc)
            if published:
                log.info("Published mission for emergency %s to %s", emergency_id, topic)
                return True
            log.warning("Mission publish attempt %s/%s failed for %s (rc=%s)", attempt, self.settings.mqtt_publish_retries, emergency_id, rc)
            time.sleep(attempt)
        self._fail_emergency(emergency_id)
        return False

    def _simulate_emergency(self, emergency_id):
        # TEMPORARY DEMO FALLBACK: remove this method once HiveMQ MQTT auth is fixed.
        # Every write below is a real transaction against the production database.
        progression = [
            (EmergencyStatus.EN_ROUTE, 3.0, 0.25, 90.0, 1, "AUTO"),
            (EmergencyStatus.APPROACHING, 3.0, 0.55, 85.0, 1, "AUTO"),
            (EmergencyStatus.ARRIVED, 3.0, 1.0, 80.0, 2, "LOITER"),
            (EmergencyStatus.AED_DELIVERED, 4.0, 1.0, 78.0, 2, "LOITER"),
            (EmergencyStatus.COMPLETED, 3.0, 1.0, 77.0, 2, "RTL"),
        ]
        record = None
        try:
            for status, delay, fraction, battery, item, mode in progression:
                time.sleep(delay)
                with SessionLocal.begin() as db:
                    emergency = db.get(Emergency, emergency_id)
                    if emergency is None or emergency.status in {EmergencyStatus.FAILED, EmergencyStatus.COMPLETED}:
                        return
                    if transition(emergency, status):
                        emergency.telemetry = {
                            "lat": emergency.lat * fraction,
                            "lng": emergency.lng * fraction,
                            "alt": 40 if status not in {EmergencyStatus.ARRIVED, EmergencyStatus.AED_DELIVERED, EmergencyStatus.COMPLETED} else 0,
                            "battery_pct": battery,
                            "mission_item_current": item,
                            "mode": mode,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    if status == EmergencyStatus.AED_DELIVERED:
                        emergency.rescue_report = {
                            "aed_delivered": True,
                            "delivery_timestamp": datetime.now(timezone.utc).isoformat(),
                            "drone_battery_at_delivery": battery,
                            "notes": "Demo fallback delivery simulation",
                        }
                    if status == EmergencyStatus.COMPLETED:
                        record = self._full_record(emergency)
            if record:
                self._post_hospital(record)
        except Exception:
            log.exception("Demo MQTT fallback failed for emergency %s", emergency_id)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        rc = getattr(reason_code, "value", reason_code)
        try:
            meaning = mqtt.connack_string(rc)
        except (AttributeError, TypeError, ValueError):
            meaning = str(reason_code)
        log.info("MQTT CONNACK rc=%s meaning=%s", rc, meaning)
        if rc != 0:
            log.error("MQTT connection refused host=%s port=%s username=%s username_bytes=%s password_bytes=%s client_id=%s protocol=MQTTv311 rc=%s meaning=%s", self.host, self.port, self.username or "<none>", len(self.username.encode("utf-8")) if self.username is not None else 0, len(self.password.encode("utf-8")), self.client_id, rc, meaning)
            return
        if self.subscribe_enabled:
            for suffix in ("status", "rescue-report"):
                self.client.subscribe(f"drone/{self.settings.drone_id}/{suffix}", qos=1)
            log.info("MQTT subscriber connected for drone %s", self.settings.drone_id)
        else:
            log.info("MQTT publisher connected for drone %s; subscriptions disabled", self.settings.drone_id)

    def _on_message(self, client, userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            if message.topic.endswith("/status"): self._handle_status(payload)
            elif message.topic.endswith("/rescue-report"): self._handle_rescue_report(payload)
        except (ValueError, TypeError, KeyError, SQLAlchemyError) as exc:
            log.exception("Discarded malformed MQTT message on %s: %s", message.topic, exc)
        except Exception:
            log.exception("Unexpected MQTT ingestion error on %s", message.topic)

    def _handle_status(self, payload):
        required = {"emergency_id","status","lat","lng","alt","battery_pct","mission_item_current","mode","timestamp"}
        if not required <= payload.keys(): raise ValueError("status message missing required fields")
        status = EmergencyStatus(payload["status"])
        with SessionLocal.begin() as db:
            emergency = db.get(Emergency, uuid.UUID(payload["emergency_id"]))
            if emergency is None or emergency.drone_id != self.settings.drone_id: raise ValueError("unknown emergency or mismatched drone")
            if transition(emergency, status): emergency.telemetry = {key: payload[key] for key in required - {"emergency_id","status"}}

    def _handle_rescue_report(self, payload):
        required = {"aed_delivered","delivery_timestamp","drone_battery_at_delivery","notes"}
        if not required <= payload.keys() or not payload["aed_delivered"]: raise ValueError("invalid rescue report")
        with SessionLocal.begin() as db:
            emergency = db.scalar(select(Emergency).where(Emergency.drone_id == self.settings.drone_id, Emergency.status.not_in([EmergencyStatus.COMPLETED, EmergencyStatus.FAILED])).order_by(Emergency.created_at.desc()))
            if emergency is None: raise ValueError("no active emergency for rescue report")
            emergency.rescue_report = payload
            transition(emergency, EmergencyStatus.AED_DELIVERED)
            record = self._full_record(emergency)
            transition(emergency, EmergencyStatus.COMPLETED)
        self._post_hospital(record)

    def _full_record(self, emergency):
        return {"id":str(emergency.id),"location":{"lat":emergency.lat,"lng":emergency.lng,"accuracy":emergency.accuracy},"name":emergency.name,"phone":emergency.phone,"timestamp":emergency.timestamp.isoformat(),"rescue_report":emergency.rescue_report}

    def _post_hospital(self, record):
        try:
            with httpx.Client(timeout=10) as client: client.post(str(self.settings.hospital_webhook_url), json=record).raise_for_status()
        except httpx.HTTPError: log.exception("Hospital webhook delivery failed")

    @staticmethod
    def _fail_emergency(emergency_id):
        try:
            with SessionLocal.begin() as db:
                emergency = db.get(Emergency, emergency_id)
                if emergency: transition(emergency, EmergencyStatus.FAILED)
        except SQLAlchemyError: log.exception("Could not mark emergency %s FAILED after publish exhaustion", emergency_id)
