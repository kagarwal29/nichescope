"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All config is loaded from environment / .env file."""

    # --- App ---
    app_env: str = "development"
    app_secret_key: str = "change-me"
    app_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    # --- Database ---
    database_url: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-detect PostgreSQL from Railway
        if not self.database_url:
            if self.app_env == "production":
                # Railway injects DATABASE_URL for PostgreSQL
                import os
                self.database_url = os.getenv(
                    "DATABASE_URL",
                    "postgresql+asyncpg://localhost/nichescope"
                )
            else:
                self.database_url = "sqlite+aiosqlite:///./nichescope.db"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- YouTube ---
    youtube_api_key: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = "http://localhost:8000/api/auth/youtube/callback"
    youtube_daily_quota: int = 10_000

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # --- Tuning ---
    rss_poll_interval_minutes: int = 15
    max_competitors_free: int = 3
    max_competitors_pro: int = 15
    max_competitors_creator_pro: int = 100
    gap_score_cache_ttl_seconds: int = 3600
    topic_cluster_max: int = 50
    video_lookback_days: int = 365

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
