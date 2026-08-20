from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://fibenchi:fibenchi@db:5432/fibenchi"
    refresh_cron: str = "0 23 * * *"
    price_provider: str = "shioaji"
    log_level: str = "INFO"
    shioaji_base_url: AnyHttpUrl = "http://shioaji:8080"
    shioaji_timeout_seconds: float = 5.0
    shioaji_max_subscriptions: int = Field(default=180, ge=1, le=200)

    model_config = {"env_prefix": ""}


settings = Settings()
