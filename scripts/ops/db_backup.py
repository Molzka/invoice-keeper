"""Back up the Compose database and restore an archive into a new database."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BACKUPS = ROOT / "backups"
AUTH = 'export PGPASSWORD="$POSTGRES_PASSWORD"; '


def container(env_file, command, *args, **kwargs):
    return subprocess.run(
        [
            "docker", "compose", "--project-directory", str(ROOT),
            "--env-file", str(env_file), "-f", str(ROOT / "compose.yaml"),
            "exec", "-T", "postgres", "sh", "-eu", "-c",
            AUTH + command, "db-backup", *args,
        ],
        cwd=ROOT,
        check=True,
        **kwargs,
    )


def backup(env_file):
    BACKUPS.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with tempfile.NamedTemporaryFile(
        dir=BACKUPS, prefix=f"postgres_{stamp}_", suffix=".dump.partial", delete=False
    ) as archive:
        partial = Path(archive.name)
    try:
        with partial.open("wb") as output:
            container(
                env_file,
                'exec pg_dump -h 127.0.0.1 -U "$POSTGRES_USER" '
                '-d "$POSTGRES_DB" -w --format=custom',
                stdin=subprocess.DEVNULL,
                stdout=output,
            )
        destination = partial.with_suffix("")
        partial.rename(destination)
        print(destination)
    finally:
        partial.unlink(missing_ok=True)


def restore(env_file, archive, database):
    with archive.open("rb") as source:
        # Reject unreadable archives before creating a database.
        container(
            env_file, "exec pg_restore --list", stdin=source,
            stdout=subprocess.DEVNULL,
        )
        source.seek(0)
        container(
            env_file,
            'if [ "$1" = "$POSTGRES_DB" ]; then '
            'echo "Refusing to restore into the working database" >&2; exit 1; fi; '
            'exec createdb -h 127.0.0.1 -U "$POSTGRES_USER" -w '
            '--maintenance-db=postgres --template=template0 -- "$1"',
            database,
            stdin=subprocess.DEVNULL,
        )
        # Never use --create or --clean: createdb must succeed first.
        try:
            container(
                env_file,
                'exec pg_restore -h 127.0.0.1 -U "$POSTGRES_USER" -w -d "$1" '
                '--single-transaction --exit-on-error --no-owner --no-privileges',
                database,
                stdin=source,
            )
        except (subprocess.CalledProcessError, KeyboardInterrupt):
            print(
                f"Restore was not confirmed. Database {database} was left in place; "
                "check it before retrying with a new name.",
                file=sys.stderr,
            )
            raise
    print(f"Restored into {database}")


def database_name(value):
    if (
        re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value) is None
        or value in {"postgres", "template0", "template1"}
    ):
        raise argparse.ArgumentTypeError(
            "Use a new database name: 1-63 lowercase ASCII letters, digits or _, "
            "starting with a letter; system database names are not allowed."
        )
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, default=ROOT / ".env",
        help="Compose environment file (default: repository .env)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("backup", help="Save a custom-format archive to backups/")
    restore_parser = commands.add_parser("restore", help="Restore into a NEW database")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("database", type=database_name)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            backup(args.env_file.resolve())
        else:
            restore(args.env_file.resolve(), args.archive, args.database)
    except (OSError, subprocess.CalledProcessError) as error:
        message = str(error) if isinstance(error, OSError) else "Docker/PostgreSQL command failed; see the error above."
        print(f"Error: {message}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
