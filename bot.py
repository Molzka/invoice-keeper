import asyncio
import html
import json
import logging
import os
from decimal import InvalidOperation
from pathlib import Path
from uuid import UUID

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramUnauthorizedError,
)
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.token import TokenValidationError
from dotenv import load_dotenv

from api import (
    ApiAuthError,
    ApiDataError,
    ApiNotConfigured,
    ApiNotFound,
    ApiRateLimited,
    ApiUnavailable,
    PaymentsClient,
)

from features import payment_card, summary_text
from formatting import format_amount, format_date

T = json.loads((Path(__file__).parent / "texts.json").read_text(encoding="utf-8"))

load_dotenv(Path(__file__).parent / ".env", override=False)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# ---------- настройки ----------

def load_chat_id():
    """CHAT_ID необязателен. Пусто или неверно: платежи отключены, публичные команды работают."""
    raw = os.environ.get("CHAT_ID", "").strip()
    if not raw:
        log.warning("CHAT_ID не задан: платежи отключены. Узнайте ID командой /id и впишите в CHAT_ID")
        return None
    try:
        return int(raw)
    except ValueError:
        log.error("CHAT_ID должен быть числом, сейчас: %r. Платежи отключены", raw)
        return None


def load_panel_url():
    """PANEL_URL необязателен. Принимаются только http(s)-адреса."""
    url = os.environ.get("PANEL_URL", "").strip()
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        log.error("PANEL_URL должен начинаться с http:// или https://, сейчас: %r. Ссылка отключена", url)
        return None
    return url


ALLOWED_CHAT = load_chat_id()

PAGE_SIZE = 5
api_client = PaymentsClient()

# ---------- роутеры ----------
# secure: данные платежей только в нашем чате. Подключается первым.
# public: команды, доступные в любом чате.

def is_allowed(chat_id) -> bool:
    return ALLOWED_CHAT is not None and chat_id == ALLOWED_CHAT


secure = Router()
secure.message.filter(lambda message: is_allowed(message.chat.id))
secure.callback_query.filter(
    lambda cb: isinstance(cb.message, Message) and is_allowed(cb.message.chat.id)
)

public = Router()


def help_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"cmd:{name}")
        for label, name in T["HELP_BUTTONS"]
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_text() -> str:
    url = load_panel_url()
    return T["PANEL"].format(url=html.escape(url, quote=False)) if url else T["PANEL_NOT_SET"]


def chat_id_text(chat_id: int) -> str:
    return T["CHAT_ID"].format(chat_id=chat_id)


# ---------- публичные команды ----------

@public.message(CommandStart())
async def start(message: Message):
    await message.answer(T["START"], reply_markup=help_keyboard())


@public.message(Command("help"))
async def help_(message: Message):
    await message.answer(T["HELP"], reply_markup=help_keyboard())


@public.message(Command("id"))
async def chat_id(message: Message):
    await message.answer(chat_id_text(message.chat.id))


@public.message(Command("site"))
async def panel(message: Message):
    await message.answer(panel_text())


@public.callback_query(F.data.in_({"cmd:start", "cmd:help", "cmd:id", "cmd:site"}))
async def cb_public(callback: CallbackQuery):
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    if callback.data in {"cmd:start", "cmd:help"}:
        text = T["START"] if callback.data == "cmd:start" else T["HELP"]
        await callback.message.answer(text, reply_markup=help_keyboard())
    elif callback.data == "cmd:id":
        await callback.message.answer(chat_id_text(callback.message.chat.id))
    else:
        await callback.message.answer(panel_text())


# Финансовые запросы в чужом чате или при незаданном CHAT_ID.
# В разрешённом чате secure обрабатывает их раньше public.
@public.message(Command("payments", "overdue", "all", "summary"))
async def msg_denied(message: Message):
    await message.answer(T["DENIED"])


@public.callback_query(
    lambda callback: callback.data in {"cmd:payments", "cmd:overdue", "cmd:all", "cmd:summary"}
    or bool(callback.data and callback.data.startswith(("pg:", "card:")))
)
async def cb_denied(callback: CallbackQuery):
    await callback.answer(T["DENIED"], show_alert=True)


# ---------- платежи (только в нашем чате) ----------

def api_error_text(error):
    if isinstance(error, ApiNotConfigured):
        return T["API_NOT_CONFIGURED"]
    if isinstance(error, ApiAuthError):
        return T["API_AUTH_FAILED"]
    if isinstance(error, ApiRateLimited):
        return T["API_RATE_LIMITED"]
    if isinstance(error, ApiNotFound):
        return T["PAYMENT_NOT_FOUND"]
    if isinstance(error, ApiDataError):
        log.error("bad payment response: %s", type(error).__name__)
        return T["BAD_DATA"]
    log.warning("payments api unavailable: %s", type(error).__name__)
    return T["API_UNAVAILABLE"]


async def build_view(kind: str, page: int):
    title, empty = T["PAYMENT_KINDS"][kind]
    page = max(page, 0)
    try:
        result = await api_client.fetch_payments(kind, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
        pages = max(1, (result["total"] + PAGE_SIZE - 1) // PAGE_SIZE)
        if page >= pages:
            page = pages - 1
            result = await api_client.fetch_payments(kind, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
            pages = max(1, (result["total"] + PAGE_SIZE - 1) // PAGE_SIZE)
    except (ApiNotConfigured, ApiUnavailable, ApiDataError) as error:
        return api_error_text(error), None

    if not result["items"]:
        return empty, help_keyboard()
    try:
        lines = [payment_card(item, T, index=page * PAGE_SIZE + index + 1)
                 for index, item in enumerate(result["items"])]
        rows = [[InlineKeyboardButton(
            text=T["BTN_CARD"].format(number=page * PAGE_SIZE + index + 1),
            callback_data=f"card:{item['id']}",
        )] for index, item in enumerate(result["items"])]
    except (ValueError, KeyError, InvalidOperation) as error:
        log.error("bad payment data: %s", type(error).__name__)
        return T["BAD_DATA"], None

    header = T["PAGE_HEADER"].format(title=title, page=page + 1, pages=pages)
    text = header + "\n\n" + "\n\n".join(lines)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=T["NAV_PREV"], callback_data=f"pg:{kind}:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text=T["NAV_NEXT"], callback_data=f"pg:{kind}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=T["BTN_MENU"], callback_data="cmd:help")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def build_card(payment_id: str):
    try:
        item = await api_client.fetch_payment(payment_id)
        return T["CARD_HEADER"] + "\n\n" + payment_card(item, T), help_keyboard()
    except (ApiNotConfigured, ApiUnavailable, ApiDataError) as error:
        return api_error_text(error), help_keyboard()
    except (ValueError, KeyError, InvalidOperation) as error:
        log.error("bad payment card: %s", type(error).__name__)
        return T["BAD_DATA"], help_keyboard()


async def build_summary():
    try:
        result = await api_client.fetch_summary()
        return summary_text(result, T), help_keyboard()
    except (ApiNotConfigured, ApiUnavailable, ApiDataError) as error:
        return api_error_text(error), help_keyboard()
    except (ValueError, KeyError, InvalidOperation) as error:
        log.error("bad payment summary: %s", type(error).__name__)
        return T["BAD_DATA"], help_keyboard()


@secure.message(Command("payments"))
async def payments(message: Message):
    text, markup = await build_view("upcoming", 0)
    await message.answer(text, reply_markup=markup)


@secure.message(Command("overdue"))
async def overdue(message: Message):
    text, markup = await build_view("overdue", 0)
    await message.answer(text, reply_markup=markup)


@secure.message(Command("all"))
async def all_payments(message: Message):
    text, markup = await build_view("all", 0)
    await message.answer(text, reply_markup=markup)


@secure.message(Command("summary"))
async def summary(message: Message):
    text, markup = await build_summary()
    await message.answer(text, reply_markup=markup)


@secure.callback_query(F.data.in_({"cmd:payments", "cmd:overdue", "cmd:all"}))
async def cb_payments(callback: CallbackQuery):
    await callback.answer()
    kind = {"cmd:payments": "upcoming", "cmd:overdue": "overdue", "cmd:all": "all"}[callback.data]
    text, markup = await build_view(kind, 0)
    await callback.message.answer(text, reply_markup=markup)


@secure.callback_query(F.data == "cmd:summary")
async def cb_summary(callback: CallbackQuery):
    await callback.answer()
    text, markup = await build_summary()
    await callback.message.answer(text, reply_markup=markup)


@secure.callback_query(F.data.startswith("card:"))
async def cb_card(callback: CallbackQuery):
    try:
        payment_id = str(UUID(callback.data.removeprefix("card:")))
    except (ValueError, TypeError, AttributeError):
        await callback.answer(T["CALLBACK_EXPIRED"], show_alert=True)
        return
    await callback.answer()
    text, markup = await build_card(payment_id)
    await callback.message.answer(text, reply_markup=markup)


@secure.callback_query(F.data.startswith("pg:"))
async def paginate(callback: CallbackQuery):
    try:
        _, kind, raw_page = callback.data.split(":")
        if kind not in T["PAYMENT_KINDS"] or not raw_page.isascii() or not raw_page.isdecimal() or len(raw_page) > 9:
            raise ValueError
        page = int(raw_page)
    except ValueError:
        await callback.answer(T["CALLBACK_EXPIRED"], show_alert=True)
        return
    await callback.answer()
    text, markup = await build_view(kind, page)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass  # "message is not modified"


# ---------- запуск ----------

async def on_error(event: ErrorEvent) -> bool:
    """Ошибка в обработчике не должна останавливать бота. Содержимое сообщений не логируется."""
    log.error(
        "ошибка в обработчике: %s", type(event.exception).__name__,
    )
    return True


async def main():
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан: укажите его в .env или в environment Compose")

    log.info(
        "конфигурация: CHAT_ID %s, PANEL_URL %s",
        "задан" if ALLOWED_CHAT is not None else "не задан",
        load_panel_url() or "не задан",
    )

    dp = Dispatcher()
    dp.errors.register(on_error)
    dp.include_router(secure)  # порядок важен: secure раньше public
    dp.include_router(public)

    try:
        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    except TokenValidationError:
        raise SystemExit("BOT_TOKEN имеет неверный формат")

    try:
        try:
            await bot.set_my_commands(
                [BotCommand(command=c, description=d) for c, d in T["COMMANDS"]]
            )
        except TelegramUnauthorizedError:
            raise
        except TelegramAPIError as exc:
            # меню команд вторично: бот работает и без него
            log.error("не удалось задать меню команд: %s", type(exc).__name__)
        await dp.start_polling(bot)
    except TelegramUnauthorizedError:
        raise SystemExit("Telegram отклонил токен (401): проверьте BOT_TOKEN, при утечке сделайте /revoke")
    finally:
        try:
            await api_client.close()
        finally:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
