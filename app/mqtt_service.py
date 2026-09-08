import json, logging, time, uuid
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
        self.tls_enabled = parsed.scheme == "mqtts"
        self.client_id = f"medidrone-backend-{settings.drone_id}"
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        if self.username is not None:
            self.client.username_pw_set(self.username, unquote(parsed.password or ""))
        if self.tls_enabled:
            self.client.tls_set()
        self.client.on_connect, self.client.on_message = self._on_connect, self._on_message

    def start(self, *, subscribe=True):
        self.subscribe_enabled = subscribe
        log.info("MQTT connecting host=%s port=%s username=%s client_id=%s protocol=MQTTv311 tls=%s", self.host, self.port, self.username or "<none>", self.client_id, self.tls_enabled)
        self.client.connect(self.host, self.port, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish_mission(self, emergency_id, items):
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

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        rc = getattr(reason_code, "value", reason_code)
        try:
            meaning = mqtt.connack_string(rc)
        except (AttributeError, TypeError, ValueError):
            meaning = str(reason_code)
        log.info("MQTT CONNACK rc=%s meaning=%s", rc, meaning)
        if rc != 0:
            log.error("MQTT connection refused host=%s port=%s username=%s client_id=%s protocol=MQTTv311 rc=%s meaning=%s", self.host, self.port, self.username or "<none>", self.client_id, rc, meaning)
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
            log.exception("Unexpected MQTT ingestion error on %s: %s", message.topic, exc)

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
            record = {"id":str(emergency.id),"location":{"lat":emergency.lat,"lng":emergency.lng,"accuracy":emergency.accuracy},"name":emergency.name,"phone":emergency.phone,"timestamp":emergency.timestamp.isoformat(),"rescue_report":payload}
            transition(emergency, EmergencyStatus.COMPLETED)
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
