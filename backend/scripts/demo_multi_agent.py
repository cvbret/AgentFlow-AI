"""Run the offline scripted demo against initialized real PostgreSQL."""
import argparse
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.demos.coordinator import DemoCoordinator


def main():
    parser = argparse.ArgumentParser(description="AI Software Engineering Assistant: scripted LLM, real durable HITL")
    parser.add_argument("--decision", choices=("approve", "reject"), help="Explicit human decision for repeatable demos; otherwise prompt")
    args = parser.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not url:
        parser.error("Set DATABASE_URL to initialized PostgreSQL; see docs/MULTI_AGENT_DEMO.md")

    def decision():
        if args.decision:
            return args.decision
        try:
            return "approve" if input("Approve staging the sample patch? [y/N] ").strip().lower() == "y" else "reject"
        except EOFError:
            return "reject"

    engine = create_engine(url)
    try:
        result = DemoCoordinator(url, sessionmaker(engine)).run(decision)
        print(f"[Final] {result.status}; staged effects={result.staged_effect_count}")
        print(result.model_dump_json(indent=2))
        return 0 if result.status in ("SUCCEEDED", "REJECTED") else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
