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
    test_database_url: SecretStr | None = None  # only used by the test suite

    # Business metric: minutes a person spends reading, sorting and copying one email
    manual_minutes_per_email: int = 3

    # Abuse protection for the public demo
    rate_limit_process_per_minute: int = 45  # per visitor IP (a full inbox run is 20)
    rate_limit_form_per_hour: int = 10  # per visitor IP
    max_daily_llm_runs: int = 600  # global ceiling on API spend
    trusted_proxy_hops: int = 0  # 0 locally; 3 on Render (Cloudflare + load balancer)

    # Author signature shown in the page footer
    author_name: str = "Felix Martinez"
    author_title: str = "Python & AI Integration Developer"


@lru_cache
def get_settings() -> Settings:
    return Settings()
