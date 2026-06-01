"""Application settings module."""

import functools

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_VERSION = "0.2.0"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WHISPER_MODEL: str = "Systran/faster-whisper-large-v3"
    DEVICE: str = "cuda"
    COMPUTE_TYPE: str = "int8_float16"
    GPU_TIMEOUT: int = 120
    GPU_CONCURRENCY: int = 1
    CORS_ALLOW_ORIGINS: list[str] = ["*"]
    LOG_LEVEL: str = "INFO"
    DEFAULT_LANGUAGE: str = "fr"
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/tokens.db"
    ADMIN_TOKEN: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@functools.lru_cache
def get_settings() -> Settings:
    """Return the settings singleton.

    Returns:
        Settings: Cached application settings instance.
    """
    return Settings()
