from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration loaded from environment variables and an optional local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_jwt_audience: str = "authenticated"
    azure_storage_account_url: str | None = None
    azure_storage_container: str | None = None
    azure_service_bus_namespace: str | None = None
    azure_service_bus_queue: str | None = None
    fal_key: str | None = None
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
