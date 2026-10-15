"""Configuration loaded from environment variables / .env.

Secrets are typed as SecretStr so they never appear in repr(), logs, or tracebacks.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "orderintel"
    postgres_password: SecretStr  # bootstrap superuser, scripts only
    oi_owner_password: SecretStr  # migrations and loader
    oi_agent_password: SecretStr  # product queries (analytics views only)
    oi_trace_password: SecretStr  # trace writer
    oi_eval_password: SecretStr  # evaluation references (raw + analytics, read-only)
    oi_injtest_password: SecretStr  # injection suite (M8)

    data_dir: Path = PROJECT_ROOT / "data" / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
