"""Run with: uv run --locked python -m app.delivery.cli --help."""

import argparse
import asyncio
import importlib
import json
import logging
from uuid import UUID

from aiogram import Bot
from sqlalchemy import select, text

from app.core.config import settings
from app.db.session import Database
from app.delivery.queue import requeue_failed, resolve_unknown
from app.delivery.schema import deliveries
from app.delivery.telegram import TelegramSender
from app.delivery.worker import DeliveryWorker


async def run(args) -> None:
    if not settings.database_url:
        raise ValueError("Set DATABASE_URL")
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as db:
            if not await db.scalar(text("SELECT to_regclass('reminder_deliveries')")):
                raise ValueError("Apply payment migration 0003 with the delivery schema first")
        if args.command == "resolve":
            async with database.session_factory() as db, db.begin():
                await resolve_unknown(
                    db,
                    args.delivery_id,
                    outcome="sent" if args.sent is not None else "not_sent",
                    telegram_message_id=args.sent,
                )
            print("Delivery decision saved.")
        elif args.command == "requeue-failed":
            async with database.session_factory() as db, db.begin():
                await requeue_failed(db, args.delivery_id)
            print("Failed delivery requeued; the worker will recheck payment eligibility.")
        elif args.command == "list":
            async with database.session_factory() as db:
                rows = (
                    (
                        await db.execute(
                            select(
                                deliveries.c.id,
                                deliveries.c.occurrence_id,
                                deliveries.c.status,
                                deliveries.c.attempt_count,
                                deliveries.c.last_error_code,
                            )
                            .where(deliveries.c.status == args.status)
                            .limit(args.limit)
                        )
                    )
                    .mappings()
                    .all()
                )
                print(json.dumps([dict(row) for row in rows], default=str))
        else:
            if not settings.bot_token or not settings.chat_id:
                raise ValueError("Set BOT_TOKEN and CHAT_ID for the worker")
            module, separator, name = args.adapter.partition(":")
            if not separator:
                raise ValueError("Adapter must be a module:factory")
            source = getattr(importlib.import_module(module), name)()
            async with Bot(settings.bot_token.get_secret_value()) as bot:
                worker = DeliveryWorker(
                    database.session_factory,
                    source,
                    TelegramSender(bot, settings.chat_id),
                    poll_seconds=args.poll_seconds,
                )
                while True:
                    try:
                        result = await worker.run_once()
                        if args.once:
                            print(json.dumps(result))
                            break
                    except Exception as exc:
                        if args.once:
                            raise
                        logging.error("Delivery cycle failed (%s)", type(exc).__name__)
                    await asyncio.sleep(args.poll_seconds)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transactional reminder delivery")
    commands = parser.add_subparsers(dest="command", required=True)
    worker = commands.add_parser("run")
    worker.add_argument("--adapter", required=True, help="Participant 2's module:factory")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--poll-seconds", type=int, default=30)
    resolve = commands.add_parser(
        "resolve", help="Explicit operator decision for an unknown result"
    )
    resolve.add_argument("delivery_id", type=UUID)
    outcome = resolve.add_mutually_exclusive_group(required=True)
    outcome.add_argument("--sent", type=int, metavar="TELEGRAM_MESSAGE_ID")
    outcome.add_argument(
        "--not-sent", action="store_true", help="Only after confirming Telegram did not send"
    )
    requeue = commands.add_parser(
        "requeue-failed", help="Requeue one failed delivery after fixing the cause; never unknown"
    )
    requeue.add_argument("delivery_id", type=UUID)
    inspect = commands.add_parser("list")
    inspect.add_argument(
        "--status",
        choices=["pending", "retry", "sent", "unknown", "failed", "cancelled", "in_flight"],
        default="unknown",
    )
    inspect.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    if getattr(args, "limit", 50) not in range(1, 101) or getattr(args, "poll_seconds", 30) < 1:
        parser.error("Use limit 1..100 and a positive poll interval")
    try:
        asyncio.run(run(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    except Exception as exc:
        # Avoid transport/DB exception text, which may include tokens or credentials.
        parser.exit(
            1,
            f"Delivery command failed ({type(exc).__name__}). Check configuration, schema and payment adapter.\n",
        )


if __name__ == "__main__":
    main()
