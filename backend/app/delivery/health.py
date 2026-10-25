"""Container health is based on a completed delivery cycle, not just a live process."""

import math
import os
import tempfile
import time
from pathlib import Path

HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "invoice-keeper-worker-heartbeat"


def record_success(path: Path = HEARTBEAT_FILE) -> None:
    stream = tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False)
    temporary = Path(stream.name)
    try:
        with stream:
            stream.write(str(time.monotonic()))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def is_healthy(path: Path = HEARTBEAT_FILE, *, max_age: float = 300) -> bool:
    try:
        age = time.monotonic() - float(path.read_text())
    except (OSError, ValueError):
        return False
    return math.isfinite(max_age) and max_age > 0 and 0 <= age <= max_age


if __name__ == "__main__":
    try:
        healthy = is_healthy(max_age=float(os.environ.get("WORKER_HEALTH_MAX_AGE_SECONDS", "300")))
    except ValueError:
        healthy = False
    if not healthy:
        raise SystemExit("Worker has no recent successful delivery cycle; inspect worker logs.")
