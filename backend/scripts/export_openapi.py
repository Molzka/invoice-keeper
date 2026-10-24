"""Export or verify the handoff schema without a database or running server."""

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if openapi.json is stale")
    args = parser.parse_args()
    application = create_app(Settings(_env_file=None, database_url=None, app_env="test"))
    expected = json.dumps(application.openapi(), ensure_ascii=False, indent=2) + "\n"
    target = BACKEND / "openapi.json"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != expected:
            print("OpenAPI is missing or stale. Run python scripts/export_openapi.py.")
            return 1
        print("OpenAPI matches the application.")
    else:
        target.write_text(expected, encoding="utf-8", newline="\n")
        print("Exported backend/openapi.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
