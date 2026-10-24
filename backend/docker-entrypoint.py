"""Build the container database URL without requiring URL-escaped passwords."""

import os
import sys

from sqlalchemy.engine import URL

if len(sys.argv) < 2:
    raise SystemExit("Specify a command to run in the backend container.")

if not os.environ.get("DATABASE_URL"):
    if not os.environ.get("POSTGRES_PASSWORD"):
        raise SystemExit("Set POSTGRES_PASSWORD in the root .env.")
    os.environ["DATABASE_URL"] = URL.create(
        "postgresql+asyncpg",
        username=os.environ.get("POSTGRES_USER", "invoice_keeper"),
        password=os.environ["POSTGRES_PASSWORD"],
        host="postgres",
        port=5432,
        database=os.environ.get("POSTGRES_DB", "invoice_keeper"),
    ).render_as_string(hide_password=False)

os.execvp(sys.argv[1], sys.argv[1:])
