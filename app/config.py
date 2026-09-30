"""Application settings loaded from environment variables (and a local .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Email Automation"
    log_level: str = "INFO"

    # Chat model. Switch provider without code changes.
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    chat_model: str = "claude-haiku-4-5"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    max_output_tokens: int = 500  # hard cap per LLM call

    database_url: SecretStr | None = None

    # Author signature shown in the page footer
    author_name: str = "Felix Martinez"
    author_title: str = "Python & AI Integration Developer"


@lru_cache
def get_settings() -> Settings:
    return Settings()
