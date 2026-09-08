# MediDrone backend

Python 3.11+ FastAPI coordination service only; it contains no App or Raspberry Pi implementation.

Copy .env.example to .env, supply real values, then run alembic upgrade head and uvicorn app.main:app --host 0.0.0.0 --port 8000. Run pytest -q for the real pymavlink MISSION_ITEM_INT generation test.

DRONE_HOME_LAT and DRONE_HOME_LNG are required because the contract requires a home-to-target-to-RTL mission but supplies no home location. APP_ORIGIN is the single permitted CORS origin.

Before handoff: deploy the Docker image to a public HTTPS URL; use a real browser at APP_ORIGIN to POST and GET an emergency; validate the broker from the backend host with mosquitto_pub/sub; then manually publish a fixed-contract status message and inspect PostgreSQL before the Pi end-to-end run.

The fixed rescue-report topic has no emergency_id, so its report is associated with the newest non-terminal emergency for DRONE_ID. Do not run concurrent emergencies for a drone until that wire contract includes an identifier.