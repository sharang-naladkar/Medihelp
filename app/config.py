from functools import lru_cache
from pydantic import AnyUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Neon CLI writes linked branch variables to .env.local; .env remains the deployment fallback.
    model_config = SettingsConfigDict(env_file=(".env", ".env.local"), extra="ignore")
    database_url: str = Field(alias="DATABASE_URL")
    database_url_unpooled: str | None = Field(default=None, alias="DATABASE_URL_UNPOOLED")
    mqtt_broker_url: str = Field(alias="MQTT_BROKER_URL")
    drone_id: str = Field(alias="DRONE_ID", min_length=1)
    drone_home_lat: float = Field(alias="DRONE_HOME_LAT", ge=-90, le=90)
    drone_home_lng: float = Field(alias="DRONE_HOME_LNG", ge=-180, le=180)
    hospital_webhook_url: AnyUrl = Field(alias="HOSPITAL_WEBHOOK_URL")
    app_origin: AnyUrl = Field(alias="APP_ORIGIN")
    mqtt_publish_retries: int = 3

@lru_cache
def get_settings() -> Settings:
    return Settings()