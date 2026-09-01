from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is invalid or missing."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    llm_api_key: str = Field(min_length=1)
    llm_base_url: str = Field(min_length=1)
    llm_model: str = Field(min_length=1)


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ConfigurationError(f"Invalid LLM configuration: {details}") from exc
