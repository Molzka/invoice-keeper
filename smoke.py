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
    return [
        (p["title"], p["amount"], p["currency"], p["due_date"], p.get("payment_url"))
        for p in items[:limit]
    ]


async def main(args) -> int:
    if args.backend:
        try:
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Локальная проверка напоминания")
    parser.add_argument("--backend", action="store_true", help="получать платежи из API вместо тестовой записи")
    parser.add_argument("--kind", choices=["upcoming", "overdue"], default="upcoming")
    parser.add_argument("--limit", type=int, default=3, help="максимум записей при --backend")
    parser.add_argument("--send", action="store_true", help="явно разрешить отправку сообщений в Telegram")
    sys.exit(asyncio.run(main(parser.parse_args())))
