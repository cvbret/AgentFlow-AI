import math
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator
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
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_attempts: int = Field(default=3, ge=1)
    llm_retry_base_delay_seconds: float = Field(default=1.0, ge=0)
    database_url: str | None = Field(default=None, min_length=1)

    @field_validator("llm_timeout_seconds")
    @classmethod
    def validate_llm_timeout_seconds(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("llm_timeout_seconds must be finite")
        return value

    @field_validator("llm_retry_base_delay_seconds")
    @classmethod
    def validate_llm_retry_base_delay_seconds(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("llm_retry_base_delay_seconds must be finite")
        return value


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
