"""Exercise registration and MFA against disposable HTTP/PostgreSQL and local Telegram.

The host runner uses the standard library. No working .env, Telegram network or unit tests.
"""

import argparse
import base64
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
    project = "invoice-keeper-access-check-" + secrets.token_hex(6)
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update(
        POSTGRES_DB="access_" + secrets.token_hex(6) + "_test",
        POSTGRES_USER="access_check",
        POSTGRES_PASSWORD=secrets.token_urlsafe(30),
        ADMIN_USERNAME="access_admin",
        ADMIN_TELEGRAM_ID="",
        ADMIN_PASSWORD=secrets.token_urlsafe(30),
        POSTGRES_PORT="0",
        FRONTEND_PORT="0",
        APP_ENV="test",
        APP_TIMEZONE=timezone,
        SESSION_COOKIE_SECURE="false",
        ALLOWED_ORIGINS='["http://access-check.local"]',
        BOT_TOKEN="123456789:" + "A" * 35,
        BOT_USERNAME="invoice_keeper_fixture_bot",
        BOT_INTERNAL_TOKEN=secrets.token_urlsafe(32),
        BOT_INTERNAL_BASE_URL="http://backend:8000",
        MFA_ENCRYPTION_KEY=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        CHAT_ID="-1001234567890",
        PANEL_URL="",
        API_BASE_URL="http://backend:8000/api/v1",
        API_ORIGIN="http://access-check.local",
        API_USERNAME="",
        API_PASSWORD="",
        API_TIMEOUT="10",
    )
    sensitive = [
        env[key]
        for key in (
            "POSTGRES_PASSWORD",
            "ADMIN_PASSWORD",
            "BOT_TOKEN",
            "BOT_INTERNAL_TOKEN",
            "MFA_ENCRYPTION_KEY",
        )
    ]

    def run(args, timeout=180):
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
        output = result.stdout + result.stderr
        for value in sensitive:
            output = output.replace(value, "[redacted]")
        if result.returncode:
            raise RuntimeError(output[-6000:])
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

        print("Isolated project: " + project, flush=True)
        try:
            images = {"backend": image, "bot": bot_image}
            for service, supplied in images.items():
                if supplied is None:
                    print("Building " + service, flush=True)
                    run(base + ["build", service], timeout=600)
                    supplied = project + "-" + service
                images[service] = run(
                    ["docker", "image", "inspect", "--format", "{{.Id}}", supplied]
                )
            mount = {
                "type": "bind",
                "source": str(root / "scripts/checks/fixtures"),
                "target": "/harness",
                "read_only": True,
            }
            services = {
                name: {
                    "image": image_id,
                    "pull_policy": "never",
                    "volumes": [mount],
                    "environment": {"PYTHONPATH": "/app:/harness"},
                }
                for name, image_id in images.items()
            }
            services["backend"]["command"] = ["python", "/harness/access_security_server.py"]
            services["bot"]["environment"].update(
                {
                    "ADMIN_USERNAME": env["ADMIN_USERNAME"],
                    "ADMIN_PASSWORD": env["ADMIN_PASSWORD"],
                }
            )
            services["access-fixture"] = {
                "image": images["backend"],
                "pull_policy": "never",
                "init": True,
                "command": ["python", "/harness/access_security_data.py"],
                "volumes": [mount],
                "read_only": True,
                "environment": {
                    key: env[key]
                    for key in (
                        "BOT_TOKEN",
                        "POSTGRES_DB",
                        "POSTGRES_USER",
                        "POSTGRES_PASSWORD",
                    )
                },
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "healthcheck": {
                    "test": [
                        "CMD",
                        "python",
                        "-c",
                        "import urllib.request; "
                        "urllib.request.urlopen('http://127.0.0.1:8082/health').close()",
                    ],
                    "interval": "1s",
                    "timeout": "3s",
                    "retries": 30,
                },
            }
            override.write_text(
                json.dumps(
                    {
                        "networks": {"default": {"internal": True}},
                        "services": services,
                    }
                ),
                encoding="utf-8",
            )
            compose("config", "--quiet")
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90", "postgres")
            if (
                run(
                    [
                        "docker",
                        "network",
                        "inspect",
                        "--format",
                        "{{.Internal}}",
                        project + "_default",
                    ]
                )
                != "true"
            ):
                raise RuntimeError("External network access must be disabled")
            for command in (
                ["alembic", "upgrade", "head"],
                ["python", "-m", "app.cli", "create-admin"],
            ):
                compose("run", "--rm", "--no-deps", "-T", "backend", *command)
            for service in ("access-fixture", "backend"):
                compose(
                    "up", "-d", "--no-build", "--no-deps", "--wait", "--wait-timeout", "90", service
                )
            for phase in ("initial", "after-restart"):
                if phase == "after-restart":
                    compose(
                        "up",
                        "-d",
                        "--no-build",
                        "--no-deps",
                        "--force-recreate",
                        "--wait",
                        "--wait-timeout",
                        "90",
                        "backend",
                    )
                print(
                    compose(
                        "run",
                        "--rm",
                        "--no-deps",
                        "-T",
                        "bot",
                        "python",
                        "/harness/access_security_probe.py",
                        phase,
                    ),
                    flush=True,
                )
            print(
                compose(
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "bot",
                    "python",
                    "/harness/telegram_payment_probe.py",
                ),
                flush=True,
            )
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
                    raise RuntimeError("Cleanup left own " + kind + " resources")
            print("PASS: own containers, database volume and internal network removed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image", help="Immutable backend image ID; otherwise build an isolated tag"
    )
    parser.add_argument(
        "--bot-image", help="Immutable bot image ID; otherwise build an isolated tag"
    )
    parser.add_argument("--timezone", default="Asia/Tokyo")
    args = parser.parse_args()
    for value in (args.image, args.bot_image):
        if value and not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            parser.error("Use a full immutable sha256 image ID")

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        check(args.image, args.bot_image, args.timezone)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        print("Access integration failed: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
