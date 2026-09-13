"""Dump the OpenAPI schema to a file without booting a server.

The frontend generates its typed client from this. Running it offline means CI
can regenerate and diff the client without standing up Postgres.

    uv run python scripts/export_openapi.py [output_path]
"""

import json
import sys
from pathlib import Path

# Allow running as a plain script (`uv run python scripts/export_openapi.py`)
# without installing the project as a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
