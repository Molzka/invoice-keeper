"""Проверка текстов напоминаний; отправка только с явным --send.

  python smoke.py                             показать локальные примеры
  python smoke.py --backend --dry-run         показать платежи из API
  python smoke.py --from-api --kind overdue --limit 5
  python smoke.py --send                      отправить локальные примеры
  python smoke.py --backend --send --limit 3   отправить платежи из API
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from api import ApiDataError, ApiNotConfigured, ApiUnavailable, PaymentsClient
from reminders import build_text, send_reminder

CASES = [
    ("Аренда офиса", "1 500,00", "RUB", "2026-11-01"),
    ("Subscription", "29.99", "USD", "2026-11-05"),
    ("Abo Strom", "84,50", "EUR", "2026-11-10"),
    ("Очень длинное название " * 30, "10", "EUR", "2026-11-15"),
    ("<b>bold</b> & _italic_ *star* [link](http://x) `code` #tag", "1", "USD", "2026-11-20"),
]


async def load_backend_cases(kind: str = "upcoming", limit: int = 3) -> list[tuple]:
    """Берёт платежи у бэкенда и приводит к аргументам send_reminder:
    (title, amount, currency, due_date, payment_url)."""
    if not 1 <= limit <= 100:
        raise ValueError("limit должен быть от 1 до 100")
    async with PaymentsClient() as client:
        page = await client.fetch_payments(kind, limit=limit, offset=0)
    return [
        (p["title"], p["amount"], p["currency"], p["due_date"], p.get("payment_url"))
        for p in page["items"]
    ]


async def main(args) -> int:
    if args.backend or args.send:
        load_dotenv(Path(__file__).parent / ".env", override=False)
    if args.backend:
        try:
            cases = await load_backend_cases(args.kind, args.limit)
        except ApiNotConfigured as exc:
            print(f"Бэкенд не настроен: {exc}. Проверьте API_BASE_URL, API_ORIGIN, API_USERNAME и API_PASSWORD")
            return 1
        except ApiUnavailable as exc:
            print(f"Бэкенд недоступен: {exc}")
            return 1
        except ApiDataError as exc:
            print(f"Неожиданный формат ответа бэкенда: {exc}")
            return 1
        if not cases:
            print("Бэкенд вернул пустой список")
            return 0
        print(f"Получено с бэкенда: {len(cases)}")
    else:
        cases = CASES

    failed = 0
    for i, case in enumerate(cases, 1):
        try:
            if not args.send:
                print(f"--- {i} ---\n{build_text(*case[:4])}")
            else:
                print(i, await send_reminder(*case))
        except ValueError as exc:  # неверный формат суммы или даты
            failed += 1
            print(f"--- {i}: пропущено, {exc}")
    return 1 if failed else 0


def positive_limit(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("limit должен быть целым от 1 до 100") from None
    if not 1 <= number <= 100:
        raise argparse.ArgumentTypeError("limit должен быть от 1 до 100")
    return number


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Проверка отправки напоминаний")
    parser.add_argument("--backend", "--from-api", dest="backend", action="store_true", help="брать платежи с бэкенда")
    parser.add_argument("--kind", choices=["upcoming", "overdue"], default="upcoming")
    parser.add_argument("--limit", type=positive_limit, default=3, help="сколько платежей показать или отправить (с --backend)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="только показать тексты (по умолчанию)")
    mode.add_argument("--send", action="store_true", help="отправить сообщения в настроенный Telegram-чат")
    sys.exit(asyncio.run(main(parser.parse_args())))
