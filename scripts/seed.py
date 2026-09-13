"""Seed reference data. Idempotent — safe to re-run.

uv run python scripts/seed.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.seeds.run import seed_all  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        created = seed_all(db)
    print("Seed complete. Rows created this run:")
    print(json.dumps(created, indent=2))


if __name__ == "__main__":
    main()
