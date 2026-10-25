"""Check real bot handlers against FastAPI/PostgreSQL, with no external Telegram calls.

python scripts/checks/check_bot_api.py [--image sha256:...] [--bot-image sha256:...]
The default builds both images. Requires Docker Compose; host Python is standard library only.
"""

import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def check(image, bot_image, timezone):
    root = Path(__file__).resolve().parents[2]
    project = "invoice-keeper-bot-check-" + secrets.token_hex(6)
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update(
        POSTGRES_DB="bot_" + secrets.token_hex(6) + "_test",
        POSTGRES_USER="bot_check",
        POSTGRES_PASSWORD=secrets.token_urlsafe(30),
        ADMIN_USERNAME="fixture_admin",
        ADMIN_TELEGRAM_ID="",
        ADMIN_PASSWORD=secrets.token_urlsafe(30),
        API_USERNAME="fixture_bot",
        API_PASSWORD=secrets.token_urlsafe(30),
        API_BASE_URL="http://backend:8000/api/v1",
        API_ORIGIN="http://bot-check.local",
        API_TIMEOUT="10",
        POSTGRES_PORT="0",
        FRONTEND_PORT="0",
        BOT_TOKEN="123456789:" + "A" * 35,
        BOT_USERNAME="",
        BOT_INTERNAL_TOKEN="",
        BOT_INTERNAL_BASE_URL="http://backend:8000",
        MFA_ENCRYPTION_KEY="",
        CHAT_ID="-1001234567890",
        PANEL_URL="",
        APP_ENV="test",
        APP_TIMEZONE=timezone,
        SESSION_COOKIE_SECURE="false",
        ALLOWED_ORIGINS='["http://bot-check.local"]',
    )
    secrets_to_mask = [
        env[key]
        for key in (
            "POSTGRES_PASSWORD",
            "ADMIN_PASSWORD",
            "API_PASSWORD",
            "BOT_TOKEN",
        )
    ]

    def redact(value):
        for secret in secrets_to_mask:
            value = value.replace(secret, "[redacted]")
        return value

    def run(args, timeout=120):
        result = subprocess.run(
            args,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(redact((result.stdout + result.stderr)[-7000:]))
        return result.stdout.strip()

    base = [
        "docker",
        "compose",
        "--project-directory",
        str(root),
        "--env-file",
        str(root / ".env.example"),
        "--project-name",
        project,
        "-f",
        str(root / "compose.yaml"),
    ]
    with tempfile.TemporaryDirectory(prefix=project + "-") as temporary:
        override = Path(temporary) / "compose.json"
        stack = base + ["-f", str(override)]

        def compose(*args, **kwargs):
            return run(stack + list(args), **kwargs)

        print(f"Isolated project: {project}", flush=True)
        try:
            images = {"backend": image, "bot": bot_image}
            for service, supplied in images.items():
                if supplied is None:
                    print(f"Building {service}...", flush=True)
                    run(base + ["build", service], timeout=600)
                    supplied = project + "-" + service
                images[service] = run(
                    ["docker", "image", "inspect", "--format", "{{.Id}}", supplied]
                )
            mount = {
                "type": "bind",
                "source": str(root / "scripts" / "checks" / "fixtures"),
                "target": "/harness",
                "read_only": True,
            }
            definition = {
                "networks": {"default": {"internal": True}},
                "services": {
                    name: {
                        "image": image_id,
                        "pull_policy": "never",
                        "volumes": [mount],
                        "environment": {"PYTHONPATH": "/app:/harness"},
                    }
                    for name, image_id in images.items()
                },
            }
            definition["services"]["bot-fixture"] = {
                "image": images["backend"],
                "pull_policy": "never",
                "init": True,
                "command": ["python", "/harness/bot_api_data.py"],
                "volumes": [mount],
                "environment": {
                    **{
                        key: "${" + key + "}"
                        for key in (
                            "POSTGRES_DB",
                            "POSTGRES_USER",
                            "POSTGRES_PASSWORD",
                            "ADMIN_USERNAME",
                            "ADMIN_PASSWORD",
                            "API_BASE_URL",
                            "API_USERNAME",
                            "API_PASSWORD",
                            "API_ORIGIN",
                            "APP_TIMEZONE",
                        )
                    },
                    "APP_ENV": "test",
                    "PYTHONPATH": "/app:/harness",
                },
                "read_only": True,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "healthcheck": {
                    "test": [
                        "CMD",
                        "python",
                        "-c",
                        "import urllib.request; "
                        "urllib.request.urlopen('http://127.0.0.1:8082/fixtures').close()",
                    ],
                    "interval": "1s",
                    "timeout": "3s",
                    "retries": 30,
                },
            }
            override.write_text(json.dumps(definition), encoding="utf-8")
            compose("config", "--quiet")
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90", "postgres")
            internal = run(
                ["docker", "network", "inspect", "--format", "{{.Internal}}", project + "_default"]
            )
            if internal != "true":
                raise RuntimeError("External network access must be disabled")
            for task in (
                ["alembic", "upgrade", "head"],
                ["python", "-m", "app.cli", "create-admin"],
            ):
                compose("run", "--rm", "--no-deps", "-T", "backend", *task)
            for service in ("backend", "bot-fixture"):
                compose(
                    "up", "-d", "--no-build", "--no-deps", "--wait", "--wait-timeout", "90", service
                )
            print(
                compose(
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "bot",
                    "python",
                    "/harness/bot_api_probe.py",
                    timeout=180,
                ),
                flush=True,
            )
        except BaseException:
            if override.exists():
                try:
                    print(
                        redact(
                            compose("logs", "--no-color", "--tail", "25", "backend", "bot-fixture")
                        ),
                        file=sys.stderr,
                    )
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
            raise
        finally:
            run(
                (stack if override.exists() else base)
                + ["down", "--volumes", "--remove-orphans", "--timeout", "10"]
            )
            for kind in ("container", "volume", "network"):
                if run(
                    [
                        "docker",
                        kind,
                        "ls",
                        "--quiet",
                        "--filter",
                        "label=com.docker.compose.project=" + project,
                    ]
                ):
                    raise RuntimeError(f"Cleanup left {kind} resources in {project}")
            print("PASS: own containers, volume and internal network removed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Existing immutable backend image ID")
    parser.add_argument("--bot-image", help="Existing immutable bot image ID")
    parser.add_argument("--timezone", default="Europe/Moscow", help="Business timezone to exercise")
    args = parser.parse_args()
    for value in (args.image, args.bot_image):
        if value and not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            parser.error("Image IDs must have the full sha256:... form")

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        check(args.image, args.bot_image, args.timezone)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Bot/API integration check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
