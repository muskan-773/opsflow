"""Application configuration loaded from environment variables / .env file."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://opsflow:opsflowdev@localhost:5432/opsflow"
    test_database_url: str = "postgresql+psycopg://opsflow:opsflowdev@localhost:5432/opsflow_test"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 480

    frontend_origin: str = "http://localhost:5173"

    def pg_url_for_tests(self) -> str:
        return self.test_database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
