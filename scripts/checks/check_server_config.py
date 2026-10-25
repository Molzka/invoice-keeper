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
    for alias, tls_default in (("", "invoice-check.example"), ("https://192.0.2.1", "192.0.2.1")):
        docker = ["docker", "run", "--rm", "--network", "none", "-e", "PUBLIC_HOST=invoice-check.example",
                  "-e", f"HTTPS_ALIASES={alias}", "-e", f"TLS_DEFAULT_NAME={tls_default}",
                  "-v", f"{root / 'docker/server/Caddyfile'}:/etc/caddy/Caddyfile:ro", proxy["image"], "caddy"]
        subprocess.run(docker + ["validate", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"], check=True)
        adapted = subprocess.check_output(docker + ["adapt", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"], text=True)
        server = json.loads(adapted)["apps"]["http"]["servers"]["srv0"]
        hosts = server["routes"][0]["match"][0]["host"]
        assert set(hosts) == ({"invoice-check.example", "192.0.2.1"} if alias else {"invoice-check.example"})
        assert all(policy.get("default_sni") == tls_default for policy in server["tls_connection_policies"])
    print("PASS: private service ports and Caddy with/without an HTTPS alias and IP certificate fallback")


if __name__ == "__main__":
    main()
