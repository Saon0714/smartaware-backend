"""Run a scheduled job by hand.

    uv run python scripts/run_job.py reindex-faq
    uv run python scripts/run_job.py purge-chat-logs

Useful for verifying a job without waiting for beat, and for the first index
after seeding FAQ content.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

JOBS = {
    "reindex-faq": "app.jobs.reindex_faq",
    "purge-chat-logs": "app.jobs.purge_chat_logs",
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        print(f"Usage: run_job.py [{' | '.join(JOBS)}]")
        return 1

    import importlib

    from app.services.rag.client import LlmUnavailable

    module = importlib.import_module(JOBS[sys.argv[1]])
    try:
        print(json.dumps(module.run(), indent=2, default=str))
    except LlmUnavailable as exc:
        # A missing key is a configuration problem, not a crash. Say so.
        print(f"Cannot run this job: {exc}", file=sys.stderr)
        print(
            "Add OPENAI_API_KEY to smartaware-backend/.env and try again.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
