"""Run explicitly: python -m app.workflows.setup (DATABASE_URL required)."""
import os

from app.workflows.checkpoint import setup_checkpoints


def main() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for checkpoint setup")
    setup_checkpoints(database_url)
    print("LangGraph PostgreSQL checkpoint setup complete.")


if __name__ == "__main__":
    main()
