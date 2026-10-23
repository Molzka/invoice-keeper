import asyncio
import html
import os

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

MAX_TITLE_LEN = 200  # лимит Telegram на сообщение — 4096, оставляем большой запас


def build_text(title, amount, currency, due_date) -> str:
    title = str(title)
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 1].rstrip() + "…"

    # Экранируем ВСЕ значения: <, >, & в данных не должны ломать HTML-разметку
    e = lambda v: html.escape(str(v), quote=False)
    return (
        "🔔 <b>Напоминание об оплате</b>\n"
        f"Название: {e(title)}\n"
        f"Сумма: {e(amount)} {e(currency)}\n"
        f"Срок: {e(due_date)}"
    )


async def send_reminder(title, amount, currency, due_date) -> int:
    """Одна попытка отправки. Возвращает message_id, ошибки пробрасывает наружу."""
    token = os.environ["BOT_TOKEN"]
    chat_id = os.environ["CHAT_ID"]

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        message = await bot.send_message(chat_id=chat_id, text=build_text(title, amount, currency, due_date))
        return message.message_id
    finally:
        await bot.session.close()  # закрываем сессию и при успехе, и при ошибке