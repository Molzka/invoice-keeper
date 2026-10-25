"""Validate the production proxy without binding ports or contacting a certificate authority."""
import json
import os
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "POSTGRES_PASSWORD": "config-check-only", "PUBLIC_HOST": "invoice-check.example"}
    result = subprocess.run(
        ["docker", "compose", "--env-file", ".env.example", "-f", "compose.yaml",
         "-f", "compose.server.yaml", "config", "--format", "json"],
        cwd=root, env=env, capture_output=True, text=True, check=True,
    )
    services = json.loads(result.stdout)["services"]
    for name in ("backend", "frontend", "postgres", "bot", "worker"):
        assert not services[name].get("ports"), f"Unexpected host ports: {name}"
    proxy = services["caddy"]
    assert {(str(port["published"]), port["protocol"]) for port in proxy["ports"]} == {("80", "tcp"), ("443", "tcp")}
    assert proxy["read_only"] and "no-new-privileges:true" in proxy["security_opt"]
    subprocess.run(
        ["docker", "run", "--rm", "--network", "none", "-e", "PUBLIC_HOST=invoice-check.example",
         "-v", f"{root / 'docker/server/Caddyfile'}:/etc/caddy/Caddyfile:ro", proxy["image"],
         "caddy", "validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
        check=True,
    )
    print("PASS: only HTTP/HTTPS are published; isolated Caddy configuration is valid")


if __name__ == "__main__":
    main()
