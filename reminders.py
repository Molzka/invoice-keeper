import html
import json
import logging
import os
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from formatting import format_amount, format_date

log = logging.getLogger(__name__)

T = json.loads((Path(__file__).parent / "texts.json").read_text(encoding="utf-8"))

MAX_TITLE_LEN = 200  # лимит Telegram на сообщение 4096, оставляем запас


def build_text(title, amount, currency, due_date) -> str:
    title = str(title)
    if len(title) > MAX_TITLE_LEN:
        title = title[: MAX_TITLE_LEN - 1].rstrip() + "…"

    # Экранируем все значения: <, > и & в данных не должны ломать HTML-разметку
    e = lambda v: html.escape(str(v), quote=False)
    return T["REMINDER"].format(
        title=e(title),
        amount=e(format_amount(amount, currency)),
        due_date=e(format_date(due_date)),
    )


def build_keyboard(payment_url=None, payment_id=None):
    rows = []
    if payment_id is not None:
        # «Оплачено» первой строкой, под сообщением. Работает, если платёж есть в базе бота
        rows.append([InlineKeyboardButton(
            text=T["FIN"]["BTN_PAID"], callback_data=f"pay:{int(payment_id)}"
        )])
    if payment_url:
        rows.append([InlineKeyboardButton(text=T["BTN_PAYMENT"], url=payment_url)])
    panel_url = (os.getenv("PANEL_URL") or "").strip()
    if panel_url.lower().startswith(("http://", "https://")):
        rows.append([InlineKeyboardButton(text=T["BTN_PANEL"], url=panel_url)])
    elif panel_url:
        log.warning("PANEL_URL должен начинаться с http:// или https://: кнопка пропущена")
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def send_reminder(title, amount, currency, due_date, payment_url=None, payment_id=None) -> int:
    """Одна попытка отправки. Возвращает message_id, ошибки пробрасывает наружу."""
    token = os.environ["BOT_TOKEN"]
    chat_id = os.environ["CHAT_ID"]

    # Формат данных проверяется до создания Bot: при ValueError сессия не открывается
    text = build_text(title, amount, currency, due_date)
    markup = build_keyboard(payment_url, payment_id)

    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        message = await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        log.info("reminder sent: message_id=%s chat_id=%s", message.message_id, chat_id)
        return message.message_id
    except Exception as exc:
        log.error("reminder failed: %s chat_id=%s", type(exc).__name__, chat_id)
        raise
    finally:
        await bot.session.close()
