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

    # LLM providers (technical design 10.2). Keys are optional so that database-only
    # scripts and tests run without them.
    llm_provider: str = "deepseek"
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_primary: str = "deepseek-flash"
    deepseek_model_comparison: str = "deepseek-v4-pro"
    llm_total_cap_usd: float = 1.90
    llm_daily_cap_usd: float = 0.40

    gemini_api_key: SecretStr | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_max_rpm: int = 12
    gemini_max_requests_per_day: int = 450

    llm_cache_dir: Path = PROJECT_ROOT / "eval" / "cache" / "llm"

    # API and public-demo protections (technical design 10.4). With no access code set,
    # every protected endpoint refuses (fail closed).
    access_code: SecretStr | None = None
    rate_limit_per_ip_per_min: int = 10
    rate_limit_global_per_min: int = 60
    # Each signed-in user's own daily model spend; admins and the operator key are limited
    # only by the overall caps above.
    user_daily_cap_usd: float = 0.05
    llm_enabled: bool = True  # kill switch: false blocks every LLM call from the API

    # Email: sign-in codes, password reset, email change, invites. "console" prints each
    # email in the API's terminal (development); "smtp" sends it, for example through Gmail
    # with an App Password; "off" sends nothing (and sign-in codes cannot be used).
    mail_mode: str = "console"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr | None = None
    mail_from_name: str = "Order Intelligence"
    # A 6-digit emailed code after the password (a trusted device skips it for 30 days).
    login_code_required: bool = True
    app_url: str = "http://localhost:3000"  # the web app, for links in emails
    api_url: str = "http://127.0.0.1:8000"  # where the UI finds the API


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
