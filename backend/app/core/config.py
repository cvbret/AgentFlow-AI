from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
    return Settings()
