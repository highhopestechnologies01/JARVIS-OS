"""
Hermes configuration — loaded from environment variables.
All settings validated by Pydantic on startup.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "Hermes"
    env: str = "production"
    secret_key: str
    log_level: str = "INFO"
    port: int = 8000

    # Database
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "jarvis"
    postgres_user: str = "jarvis"
    postgres_password: str

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # Twilio
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    thomas_phone_number: str = ""

    # Email
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notification_email: str = ""

    # Notion
    notion_api_key: str = ""
    notion_dashboard_page_id: str = ""

    # n8n
    n8n_webhook_url: str = "http://n8n:5678"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def is_production(self) -> bool:
        return self.env == "production"


# Singleton — import this everywhere
settings = Settings()
