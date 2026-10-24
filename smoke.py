"""Локальная проверка напоминания без базы данных и без отправки в Telegram.

Запуск:
  python smoke.py                  проверить одну тестовую запись локально
  python smoke.py --backend        взять реальные платежи из API и показать тексты
  python smoke.py --send            отправить тестовую запись в Telegram (явное подтверждение флагом)
  python smoke.py --backend --send  отправить реальные платежи из API
"""
import argparse
import asyncio
import html
import json
import logging
import os
import sys
from pathlib import Path

from formatting import format_amount, format_date

<<<<<<< HEAD
load_dotenv(Path(__file__).parent / ".env", override=False)

from api import ApiDataError, ApiNotConfigured, ApiUnavailable, PaymentsClient  # noqa: E402
from reminders import build_text, send_reminder  # noqa: E402

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
=======
BASE_DIR = Path(__file__).parent

# Единственная локальная тестовая запись. Не сохраняется в БД и не отправляется без --send.
TEST_PAYMENT = {
    "title": "Тестовый счёт №001",
    "amount": "1500.00",
    "currency": "RUB",
    "due_date": "2026-11-01",
    # Демонстрационная ссылка: кнопка видна, но это не настоящая оплата.
    "payment_url": "https://example.com/test-payment",
}


def build_local_text(title, amount, currency, due_date) -> str:
    texts = json.loads((BASE_DIR / "texts.json").read_text(encoding="utf-8"))
    title = str(title)
    if len(title) > 200:
        title = title[:199].rstrip() + "…"
    return texts["REMINDER"].format(
        title=html.escape(title, quote=False),
        amount=html.escape(format_amount(amount, currency), quote=False),
        due_date=html.escape(format_date(due_date), quote=False),
    )


async def load_api_cases(kind: str = "upcoming", limit: int = 3) -> list[tuple]:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)
    from api import ApiDataError, ApiNotConfigured, ApiUnavailable, fetch_payments
    items = await fetch_payments(kind)
>>>>>>> 421c8c2 (сделал кнопки проверяй,+ есть кнопка для календаря,но надо подключить к беку,+ оставшееся,что надо подключить типа платежей)
    return [
        (p["title"], p["amount"], p["currency"], p["due_date"], p.get("payment_url"))
        for p in page["items"]
    ]


async def main(args) -> int:
    if args.backend:
        try:
<<<<<<< HEAD
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
=======
            cases = await load_api_cases(args.kind, args.limit)
        except Exception as exc:
            from api import ApiDataError, ApiNotConfigured, ApiUnavailable
            if isinstance(exc, ApiNotConfigured):
                print(f"Сервис не настроен: {exc}. Для локального теста запустите python smoke.py без --backend.")
                return 1
            if isinstance(exc, ApiUnavailable):
                print(f"Сервис недоступен: {exc}")
                return 1
            if isinstance(exc, ApiDataError):
                print(f"Неверный формат данных: {exc}")
                return 1
            raise
        
>>>>>>> 421c8c2 (сделал кнопки проверяй,+ есть кнопка для календаря,но надо подключить к беку,+ оставшееся,что надо подключить типа платежей)
        if not cases:
            print("Список счетов пуст")
            return 0
    else:
        cases = [(TEST_PAYMENT["title"], TEST_PAYMENT["amount"], TEST_PAYMENT["currency"], TEST_PAYMENT["due_date"], TEST_PAYMENT["payment_url"])]

    failed = 0
    for i, case in enumerate(cases, 1):
        try:
            if args.send:
                from reminders import send_reminder
                from dotenv import load_dotenv
                load_dotenv(BASE_DIR / ".env", override=True)
                message_id = await send_reminder(*case)
                print(f"Сообщение отправлено, message_id={message_id}")
            else:
                print(f"--- Тест {i} (локально, без отправки) ---")
                print(build_local_text(*case[:4]))
                print("OK: форматирование прошло успешно")
        except (ValueError, KeyError) as exc:
            failed += 1
            print(f"Тест {i} не пройден: {exc}")
        except Exception as exc:
            failed += 1
            print(f"Ошибка отправки/проверки: {type(exc).__name__}: {exc}")
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
    parser = argparse.ArgumentParser(description="Локальная проверка напоминания")
    parser.add_argument("--backend", action="store_true", help="получать платежи из API вместо тестовой записи")
    parser.add_argument("--kind", choices=["upcoming", "overdue"], default="upcoming")
<<<<<<< HEAD
    parser.add_argument("--limit", type=positive_limit, default=3, help="сколько платежей отправить (с --backend)")
    parser.add_argument("--dry-run", action="store_true", help="только показать тексты")
=======
    parser.add_argument("--limit", type=int, default=3, help="максимум записей при --backend")
    parser.add_argument("--send", action="store_true", help="явно разрешить отправку сообщений в Telegram")
>>>>>>> 421c8c2 (сделал кнопки проверяй,+ есть кнопка для календаря,но надо подключить к беку,+ оставшееся,что надо подключить типа платежей)
    sys.exit(asyncio.run(main(parser.parse_args())))
