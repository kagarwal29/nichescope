"""Application configuration via environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Package lives at …/nichescope/config.py → repo root is parent.parent.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load `.env` before Settings() regardless of process cwd (Docker WORKDIR=/app).
_ENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(_ENV_PATH, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = ""

    # YouTube
    youtube_api_key: str = ""
    youtube_daily_quota: int = 10_000

    # Telegram
    telegram_bot_token: str = ""
    # Webhook mode: set to the full public HTTPS URL Telegram should POST to.
    # e.g. https://yourserver.com/webhook
    # Leave empty to use long-polling (needs outbound access to api.telegram.org).
    telegram_webhook_url: str = ""
    # Optional: a random string Telegram sends as X-Telegram-Bot-Api-Secret-Token header.
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    telegram_webhook_secret: str = ""

    # Uber GenAI (OpenAI-compatible chat completions)
    genai_chat_url: str = "https://genai-api.uberinternal.com/v1/chat/completions"
    genai_token: str = ""  # Bearer token (JWT); no "Bearer " prefix in .env
    # Must be a model id your GenAI project can access (no single default — gpt-4 often 403s).
    genai_model: str = ""
    # Combined CA bundle (standard public CAs + Uber/Zscaler corporate CAs).
    # Overridden at runtime by SSL_CERT_FILE env var (set in docker-compose).
    ssl_ca_bundle: str = "/app/certs/combined-ca-bundle.pem"

    # Moat MVP: competitor watchlist digest (UTC hour 0–23)
    digest_enabled: bool = True
    digest_hour_utc: int = 9

    @model_validator(mode="after")
    def legacy_openai_api_key_as_genai_token(self):
        """Support older deployments that still set OPENAI_API_KEY."""
        if not self.genai_token.strip():
            legacy = os.getenv("OPENAI_API_KEY", "").strip()
            if legacy:
                self.genai_token = legacy
        return self

    def __init__(self, **data):
        super().__init__(**data)
        if not self.database_url:
            if self.app_env == "production":
                self.database_url = os.getenv(
                    "DATABASE_URL",
                    "postgresql+asyncpg://localhost/nichescope",
                )
            else:
                p = _PROJECT_ROOT / "data" / "nichescope.db"
                p.parent.mkdir(parents=True, exist_ok=True)
                self.database_url = f"sqlite+aiosqlite:///{p.resolve().as_posix()}"


settings = Settings()
