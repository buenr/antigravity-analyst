"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Antigravity Data Analyst"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Google Cloud
    gcp_project_id: str
    gcs_bucket_name: str
    google_application_credentials: Optional[str] = None

    # Gemini API
    gemini_api_key: str

    # File Upload
    max_file_size_mb: int = 50
    allowed_extensions: str = ".csv,.xlsx,.xls,.parquet,.json,.jsonl"

    # Session
    session_timeout_minutes: int = 15

    @property
    def max_file_size_bytes(self) -> int:
        """Convert MB to bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def allowed_extensions_list(self) -> list[str]:
        """Get allowed extensions as a list."""
        return [ext.strip() for ext in self.allowed_extensions.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
