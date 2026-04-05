from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Allow mutation so tests can monkeypatch individual fields
        frozen=False,
    )

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_url: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # Google Sheets
    google_service_account_json: str = ""
    spreadsheet_id: str = ""

    # Database
    database_path: str = "data/kitchen.db"

    # Admin chat IDs (Evan's chat_id gets admin commands)
    admin_chat_ids: list[int] = []

    # Models
    intent_classifier_model: str = "claude-haiku-4-5"
    main_model: str = "claude-opus-4-6"

    # Guardrails
    daily_cost_ceiling_usd: float = 5.0
    rate_limit_messages_per_minute: int = 10
    llm_timeout_seconds: int = 30


settings = Settings()
