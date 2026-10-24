"""Exercise the Compose reminder worker against a disposable DB and local Telegram stub.

Run from any directory: python scripts/check_reminder_worker.py [--image sha256:...]
Requires Docker Compose; host Python uses only the standard library. Never reads .env.
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
import time
from pathlib import Path


def check(image=None, timezone="Europe/Moscow"):
    root = Path(__file__).resolve().parents[1]
    project = "invoice-keeper-worker-check-" + secrets.token_hex(6)
    env = {key: value for key, value in os.environ.items() if not key.startswith("COMPOSE_")}
    env.update(
        POSTGRES_DB="worker_" + secrets.token_hex(6) + "_test",
        POSTGRES_USER="worker_check",
        POSTGRES_PASSWORD=secrets.token_urlsafe(30),
        ADMIN_USERNAME="worker_admin",
        ADMIN_PASSWORD=secrets.token_urlsafe(30),
        POSTGRES_PORT="0",
        FRONTEND_PORT="0",
        BOT_TOKEN="123456789:" + "A" * 35,
        CHAT_ID="-1001234567890",
        PANEL_URL="",
        APP_ENV="test",
        APP_TIMEZONE=timezone,
        SESSION_COOKIE_SECURE="false",
        ALLOWED_ORIGINS='["http://127.0.0.1:8000"]',
        REMINDER_POLL_SECONDS="1",
    )
    secret_values = [env[key] for key in ("POSTGRES_PASSWORD", "ADMIN_PASSWORD", "BOT_TOKEN")]

    def redact(value):
        for secret in secret_values:
            value = value.replace(secret, "[redacted]")
        return value

    def run(args, *, timeout=120, data=None):
        result = subprocess.run(
            args,
            check=False,
            env=env,
            cwd=root,
            input=data,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if result.returncode:
            raise RuntimeError(redact((result.stdout + result.stderr)[-6000:]))
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
        wrapped = Path(temporary) / "wrapped.json"
        stack = base + ["-f", str(override)]

        def compose(*args, **kwargs):
            return run(stack + list(args), **kwargs)

        def probe(mode, state=None):
            output = compose(
                "exec",
                "-T",
                "backend",
                "python",
                "/app/docker-entrypoint.py",
                "python",
                "/harness/reminder_probe.py",
                mode,
                data=json.dumps(state or {}),
                timeout=120,
            )
            return json.loads(output)

        def inspect_worker():
            container = compose("ps", "--quiet", "worker")
            if not container:
                raise RuntimeError("Worker service is not running")
            state = json.loads(
                run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        '{"running":{{.State.Running}},"restarts":{{.RestartCount}},'
                        '"started":{{json .State.StartedAt}},"command":{{json .Config.Cmd}}}',
                        container,
                    ]
                )
            )
            if not state["running"] or state["restarts"] != 0:
                raise RuntimeError("Worker stopped or entered a restart loop")
            return state

        print(f"Isolated project: {project}", flush=True)
        # Only this generated project/network/volume can be removed in finally.
        try:
            config = json.loads(run(base + ["config", "--format", "json"]))
            command = config["services"]["worker"]["command"]
            if command[:3] != ["python", "-m", "app.delivery.cli"]:
                raise RuntimeError("Unexpected production worker command; review the harness")
            if "--once" in command:
                raise RuntimeError("Compose worker must run continuously")
            if image is None:
                print("Building the worker image...", flush=True)
                run(base + ["build", "worker"], timeout=600)
                image = project + "-worker"
            image = run(["docker", "image", "inspect", "--format", "{{.Id}}", image])
            fixture_mount = {
                "type": "bind",
                "source": str(root / "scripts" / "fixtures"),
                "target": "/harness",
                "read_only": True,
            }
            definition = {
                "networks": {"default": {"internal": True}},
                "services": {
                    name: {
                        "image": image,
                        "pull_policy": "never",
                        "volumes": [fixture_mount],
                        "environment": {"PYTHONPATH": "/app"},
                    }
                    for name in ("backend", "worker")
                },
            }
            definition["services"]["telegram-stub"] = {
                "image": image,
                "pull_policy": "never",
                "init": True,
                "entrypoint": ["python", "/harness/reminder_transport.py", "stub"],
                "command": [],
                "volumes": [fixture_mount],
                "read_only": True,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "healthcheck": {
                    "test": [
                        "CMD",
                        "python",
                        "-c",
                        "import urllib.request; "
                        "urllib.request.urlopen('http://127.0.0.1:8081/requests').close()",
                    ],
                    "interval": "1s",
                    "timeout": "2s",
                    "retries": 20,
                },
            }
            override.write_text(json.dumps(definition), encoding="utf-8")
            compose("config", "--quiet")
            compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90", "postgres")
            network = json.loads(
                run(
                    [
                        "docker",
                        "network",
                        "inspect",
                        "--format",
                        "{{json .Internal}}",
                        project + "_default",
                    ]
                )
            )
            if network is not True:
                raise RuntimeError("Test network must be internal: external Telegram is forbidden")
            for task in (
                ["alembic", "upgrade", "head"],
                ["alembic", "check"],
                ["python", "-m", "app.cli", "create-admin"],
            ):
                compose("run", "--rm", "--no-deps", "-T", "backend", *task)
            compose(
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "90",
                "backend",
            )
            future = probe("prepare-future")
            compose("up", "-d", "--no-build", "--no-deps", "worker")
            native = inspect_worker()
            if native["command"] != command:
                raise RuntimeError("Native worker command differs from the Compose configuration")
            probe("verify-future", future)
            inspect_worker()
            print(
                "PASS: unmodified worker starts and restores a missing future period",
                flush=True,
            )
            compose("stop", "--timeout", "10", "worker")

            scenario = probe("prepare-dispatch")
            wrapped.write_text(
                json.dumps(
                    {
                        "services": {
                            "worker": {
                                "command": [
                                    "python",
                                    "/harness/reminder_transport.py",
                                    "worker",
                                    *command[3:],
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            stack.extend(["-f", str(wrapped)])
            compose(
                "up",
                "-d",
                "--no-build",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "30",
                "telegram-stub",
            )
            compose("up", "-d", "--no-build", "--no-deps", "worker")
            first = probe("verify-dispatch", scenario)
            before = inspect_worker()
            print(
                "PASS: due reminders confirmed; paid/stopped skipped; missing due period restored",
                flush=True,
            )
            compose("stop", "--timeout", "10", "worker")
            probe("erase-future", future)
            compose("restart", "--timeout", "10", "worker")
            after = inspect_worker()
            if before["started"] == after["started"]:
                raise RuntimeError("Worker was not restarted")
            probe("verify-future", future)
            # The restarted process has now run recovery; observe more polling intervals, with confirmed IDs/message IDs compared below.
            time.sleep(4)
            repeated = probe("verify-dispatch", scenario)
            if first != repeated:
                raise RuntimeError("Confirmed deliveries changed across restart")
            inspect_worker()
            print(
                "PASS: restart preserves confirmations and produces no duplicate HTTP sends",
                flush=True,
            )
        except BaseException:
            if override.exists():
                try:
                    print(
                        redact(
                            compose(
                                "logs",
                                "--no-color",
                                "--tail",
                                "35",
                                "worker",
                                "backend",
                                "telegram-stub",
                            )
                        ),
                        file=sys.stderr,
                    )
                except (RuntimeError, subprocess.TimeoutExpired):
                    pass
            raise
        finally:
            cleanup = stack if override.exists() else base
            run(cleanup + ["down", "--volumes", "--remove-orphans", "--timeout", "10"])
            label = "label=com.docker.compose.project=" + project
            for kind in ("container", "volume", "network"):
                remaining = run(["docker", kind, "ls", "--quiet", "--filter", label])
                if remaining:
                    raise RuntimeError(f"Cleanup left {kind} resources in {project}")
            print("PASS: own containers, volume and internal network removed", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Existing immutable backend/worker image ID (sha256:...)")
    parser.add_argument("--timezone", default="Europe/Moscow", help="Business timezone to exercise")
    args = parser.parse_args()
    if args.image and not re.fullmatch(r"sha256:[0-9a-f]{64}", args.image):
        parser.error("--image must be a full immutable sha256 image ID")

    def interrupted(_signal, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        check(args.image, args.timezone)
    except KeyboardInterrupt:
        print("Worker integration check interrupted", file=sys.stderr)
        return 130
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Worker integration check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
