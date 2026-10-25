import time

from app.delivery.health import is_healthy, record_success


def test_worker_health_requires_recent_success(tmp_path):
    heartbeat = tmp_path / "heartbeat"
    assert not is_healthy(heartbeat, max_age=300)
    record_success(heartbeat)
    assert is_healthy(heartbeat, max_age=300)
    for value in (str(time.monotonic() - 301), str(time.monotonic() + 301), "nan", "broken"):
        heartbeat.write_text(value)
        assert not is_healthy(heartbeat, max_age=300)
