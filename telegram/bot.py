import asyncio
import html
import json
import logging
import os
from decimal import InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
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
from api import (
    ApiAuthError,
    ApiDataError,
    ApiNotConfigured,
    ApiNotFound,
    ApiRateLimited,
    ApiUnavailable,
    PaymentsClient,
)
from dotenv import load_dotenv
from features import payment_card, payment_list_item, summary_text

T = json.loads((Path(__file__).parent / "texts.json").read_text(encoding="utf-8"))

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# ---------- настройки ----------


def load_chat_id():
    """CHAT_ID необязателен. Пусто или неверно: платежи отключены, публичные команды работают."""
    raw = os.environ.get("CHAT_ID", "").strip()
    if not raw:
        log.warning(
            "CHAT_ID не задан: платежи отключены. Узнайте ID командой /id и впишите в CHAT_ID"
        )
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
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not any(char.isspace() for char in url)
        )
        _ = parsed.port
    except ValueError:
        valid = False
    if not valid:
        log.error(
            "PANEL_URL должен быть полным http(s)-адресом без учётных данных. Ссылка отключена"
        )
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


def panel_button():
    url = load_panel_url()
    return InlineKeyboardButton(text=T["BTN_PANEL"], url=url) if url else None


def help_keyboard(chat_id) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"cmd:{name}")
        for label, name in T["HELP_BUTTONS"]
        if is_allowed(chat_id)
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    if button := panel_button():
        rows.append([button])
    rows.append([InlineKeyboardButton(text=T["BTN_HELP"], callback_data="cmd:help")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def view_keyboard(retry, *, back=None, panel=False):
    rows = [[InlineKeyboardButton(text=T["BTN_REFRESH"], callback_data=retry)]]
    if back:
        kind, page = back
        rows.append(
            [
                InlineKeyboardButton(
                    text=T["BTN_BACK_LIST"].format(page=page + 1),
                    callback_data=f"pg:{kind}:{page}",
                )
            ]
        )
    if panel and (button := panel_button()):
        rows.append([button])
    rows.append([InlineKeyboardButton(text=T["BTN_MENU"], callback_data="cmd:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def error_keyboard(retry, *, back=None):
    markup = view_keyboard(retry, back=back)
    markup.inline_keyboard[0][0].text = T["BTN_RETRY"]
    return markup


def start_text(chat_id):
    return T["START"] if is_allowed(chat_id) else T["START_PRIVATE"]


def support_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=T["BTN_CHAT_ID"], callback_data="cmd:id")],
            [InlineKeyboardButton(text=T["BTN_PANEL"], callback_data="cmd:site")],
            [InlineKeyboardButton(text=T["BTN_MENU"], callback_data="cmd:start")],
        ]
    )


async def show_callback(callback, text, markup, *, new_message=False):
    """Navigate in place; keep reminder snapshots intact when opening legacy cards."""
    if new_message:
        await callback.message.answer(text, reply_markup=markup)
        return
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as error:
        description = error.message.lower()
        if "message is not modified" in description:
            return
        if "message to edit not found" in description or "message can't be edited" in description:
            await callback.message.answer(text, reply_markup=markup)
            return
        raise


async def acknowledge(callback, text=None, *, show_alert=False):
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest as error:
        description = error.message.lower()
        if "query is too old" in description or "query id is invalid" in description:
            return False
        raise
    return True


def panel_text() -> str:
    url = load_panel_url()
    return T["PANEL"].format(url=html.escape(url, quote=False)) if url else T["PANEL_NOT_SET"]


def chat_id_text(chat_id: int) -> str:
    return T["CHAT_ID"].format(chat_id=chat_id)


# ---------- публичные команды ----------


@public.message(CommandStart())
@public.message(Command("menu"))
async def start(message: Message):
    await message.answer(start_text(message.chat.id), reply_markup=help_keyboard(message.chat.id))


@public.message(Command("help"))
async def help_(message: Message):
    await message.answer(T["HELP"], reply_markup=support_keyboard())


@public.message(Command("id"))
async def chat_id(message: Message):
    await message.answer(chat_id_text(message.chat.id), reply_markup=support_keyboard())


@public.message(Command("site"))
async def panel(message: Message):
    await message.answer(panel_text(), reply_markup=help_keyboard(message.chat.id))


@public.callback_query(lambda callback: not isinstance(callback.message, Message))
async def cb_inaccessible(callback: CallbackQuery):
    await acknowledge(callback, T["CALLBACK_EXPIRED"], show_alert=True)


@public.callback_query(F.data.in_({"cmd:start", "cmd:help", "cmd:id", "cmd:site"}))
async def cb_public(callback: CallbackQuery):
    if not await acknowledge(callback):
        return
    if callback.data == "cmd:start":
        await show_callback(
            callback,
            start_text(callback.message.chat.id),
            help_keyboard(callback.message.chat.id),
        )
    elif callback.data == "cmd:help":
        await show_callback(callback, T["HELP"], support_keyboard())
    elif callback.data == "cmd:id":
        await show_callback(callback, chat_id_text(callback.message.chat.id), support_keyboard())
    else:
        await show_callback(callback, panel_text(), help_keyboard(callback.message.chat.id))


# Финансовые запросы в чужом чате или при незаданном CHAT_ID.
# В разрешённом чате secure обрабатывает их раньше public.
@public.message(Command("payments", "overdue", "all", "summary"))
async def msg_denied(message: Message):
    await message.answer(T["DENIED"])


@public.callback_query(
    lambda callback: (
        callback.data in {"cmd:payments", "cmd:overdue", "cmd:all", "cmd:summary"}
        or bool(callback.data and callback.data.startswith(("pg:", "card:")))
    )
)
async def cb_denied(callback: CallbackQuery):
    await acknowledge(callback, T["DENIED"], show_alert=True)


@public.callback_query()
async def cb_unknown(callback: CallbackQuery):
    await acknowledge(callback, T["CALLBACK_EXPIRED"], show_alert=True)


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
        return api_error_text(error), error_keyboard(f"pg:{kind}:{page}")

    if not result["items"]:
        return empty, view_keyboard(f"pg:{kind}:0")
    try:
        lines, rows = [], []
        for index, item in enumerate(result["items"]):
            number = page * PAGE_SIZE + index + 1
            lines.append(payment_list_item(item, T, index=number))
            label = " ".join(item["title"].split())
            if len(label) > 32:
                label = label[:32].rstrip() + "…"
            rows.append(
                [
                    InlineKeyboardButton(
                        text=T["BTN_CARD"].format(number=number, title=label),
                        callback_data=f"card:{item['id']}:{kind}:{page}",
                    )
                ]
            )
    except (ValueError, KeyError, InvalidOperation) as error:
        log.error("bad payment data: %s", type(error).__name__)
        return T["BAD_DATA"], error_keyboard(f"pg:{kind}:{page}")

    header = T["PAGE_HEADER"].format(
        title=title,
        page=page + 1,
        pages=pages,
        total=result["total"],
        first=page * PAGE_SIZE + 1,
        last=page * PAGE_SIZE + len(result["items"]),
    )
    text = header + "\n\n" + "\n\n".join(lines)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text=T["NAV_PREV"], callback_data=f"pg:{kind}:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text=T["NAV_NEXT"], callback_data=f"pg:{kind}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.extend(view_keyboard(f"pg:{kind}:{page}").inline_keyboard)
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def build_card(payment_id: str, kind="all", page=0):
    retry = f"card:{payment_id}:{kind}:{page}"
    try:
        item = await api_client.fetch_payment(payment_id)
        return (
            T["CARD_HEADER"] + "\n\n" + payment_card(item, T) + T["CARD_HINT"],
            view_keyboard(retry, back=(kind, page), panel=True),
        )
    except (ApiNotConfigured, ApiUnavailable, ApiDataError) as error:
        return api_error_text(error), error_keyboard(retry, back=(kind, page))
    except (ValueError, KeyError, InvalidOperation) as error:
        log.error("bad payment card: %s", type(error).__name__)
        return T["BAD_DATA"], error_keyboard(retry, back=(kind, page))


async def build_summary():
    try:
        result = await api_client.fetch_summary()
        return summary_text(result, T), view_keyboard("cmd:summary", panel=True)
    except (ApiNotConfigured, ApiUnavailable, ApiDataError) as error:
        return api_error_text(error), error_keyboard("cmd:summary")
    except (ValueError, KeyError, InvalidOperation) as error:
        log.error("bad payment summary: %s", type(error).__name__)
        return T["BAD_DATA"], error_keyboard("cmd:summary")


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
    if not await acknowledge(callback):
        return
    kind = {"cmd:payments": "upcoming", "cmd:overdue": "overdue", "cmd:all": "all"}[callback.data]
    text, markup = await build_view(kind, 0)
    await show_callback(callback, text, markup)


@secure.callback_query(F.data == "cmd:summary")
async def cb_summary(callback: CallbackQuery):
    if not await acknowledge(callback):
        return
    text, markup = await build_summary()
    await show_callback(callback, text, markup)


@secure.callback_query(F.data.startswith("card:"))
async def cb_card(callback: CallbackQuery):
    try:
        parts = callback.data.split(":")
        if len(parts) not in {2, 4}:
            raise ValueError
        payment_id = str(UUID(parts[1]))
        kind, page = parse_page(parts[2], parts[3]) if len(parts) == 4 else ("all", 0)
    except (ValueError, TypeError, AttributeError):
        await acknowledge(callback, T["CALLBACK_EXPIRED"], show_alert=True)
        return
    if not await acknowledge(callback):
        return
    text, markup = await build_card(payment_id, kind, page)
    await show_callback(callback, text, markup, new_message=len(parts) == 2)


def parse_page(kind, raw_page):
    if (
        kind not in T["PAYMENT_KINDS"]
        or not raw_page.isascii()
        or not raw_page.isdecimal()
        or len(raw_page) > 9
    ):
        raise ValueError
    return kind, int(raw_page)


@secure.callback_query(F.data.startswith("pg:"))
async def paginate(callback: CallbackQuery):
    try:
        _, kind, raw_page = callback.data.split(":")
        kind, page = parse_page(kind, raw_page)
    except ValueError:
        await acknowledge(callback, T["CALLBACK_EXPIRED"], show_alert=True)
        return
    if not await acknowledge(callback):
        return
    text, markup = await build_view(kind, page)
    await show_callback(callback, text, markup)


# ---------- запуск ----------


async def on_error(event: ErrorEvent) -> bool:
    """Ошибка в обработчике не должна останавливать бота. Содержимое сообщений не логируется."""
    log.error(
        "ошибка в обработчике: %s",
        type(event.exception).__name__,
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
        raise SystemExit(
            "Telegram отклонил токен (401): проверьте BOT_TOKEN, при утечке сделайте /revoke"
        )
    finally:
        try:
            await api_client.close()
        finally:
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
