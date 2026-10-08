from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

RECONSTRUCTION_SOURCE_SAS_PICKUP_BUFFER_MINUTES = 5


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
    upload_max_image_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    upload_quota_limit: int = Field(default=30, gt=0)
    upload_quota_window_hours: int = Field(default=24, gt=0)
    upload_pending_lifetime_hours: int = Field(default=24, gt=0)
    upload_sas_lifetime_minutes: int = Field(default=10, gt=0)
    artifact_read_url_lifetime_minutes: int = Field(default=10, gt=0)
    azure_service_bus_namespace: str | None = None
    azure_service_bus_queue: str | None = None
    azure_service_bus_generation_queue: str | None = None
    fal_key: str | None = None
    reconstruction_poll_interval_seconds: int = Field(default=10, gt=0)
    reconstruction_max_runtime_minutes: int = Field(default=20, gt=0)
    reconstruction_max_model_size_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    reconstruction_source_sas_lifetime_minutes: int = Field(default=25, gt=0)
    reconstruction_http_timeout_seconds: int = Field(default=30, gt=0)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @model_validator(mode="after")
    def validate_reconstruction_source_sas_lifetime(self) -> "Settings":
        minimum_lifetime = (
            self.reconstruction_max_runtime_minutes
            + RECONSTRUCTION_SOURCE_SAS_PICKUP_BUFFER_MINUTES
        )
        if self.reconstruction_source_sas_lifetime_minutes < minimum_lifetime:
            raise ValueError(
                "RECONSTRUCTION_SOURCE_SAS_LIFETIME_MINUTES must cover the maximum "
                "reconstruction runtime plus five minutes."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
