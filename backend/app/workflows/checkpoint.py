from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy.engine import make_url


def postgres_connection_string(database_url: str) -> str:
    """Adapt the repository SQLAlchemy URL to a psycopg/libpq PostgreSQL URI."""
    url = make_url(database_url)
    if url.drivername not in ("postgresql", "postgresql+psycopg"):
        raise ValueError("Workflow checkpoints require PostgreSQL with psycopg")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


@contextmanager
def open_checkpointer(database_url: str) -> Iterator[PostgresSaver]:
    """Own one sync connection; normal usage deliberately does not run setup."""
    with PostgresSaver.from_conn_string(postgres_connection_string(database_url)) as saver:
        yield saver


def setup_checkpoints(database_url: str) -> None:
    """Explicit deployment initialization; framework owns its checkpoint schema."""
    with open_checkpointer(database_url) as saver:
        saver.setup()
