from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import ConfigurationError, Settings, get_settings


def create_engine_from_settings(settings: Settings | None = None) -> Engine:
    resolved_settings = settings or get_settings()
    if not resolved_settings.database_url:
        raise ConfigurationError("DATABASE_URL is required")
    return create_engine(resolved_settings.database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=create_engine_from_settings(),
        expire_on_commit=False,
    )
