"""Shared environment-backed application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Settings shared by the API, migration environment, and seed command."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://returnpilot:change-me@localhost:5432/returnpilot"
    mcp_server_url: str = "http://127.0.0.1:8001/mcp"
    grant_signing_secret: SecretStr | None = None
    mcp_shared_secret: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_max_iterations: int = 4
    gemini_timeout_seconds: float = 20.0
    demo_session_cookie: str = "returnpilot_demo_session"
    demo_session_ttl_seconds: int = 60 * 60 * 12


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
