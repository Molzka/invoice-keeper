import asyncio
import html
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

dp = Dispatcher()


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет! Я бот Invoice Keeper: присылаю напоминания о платежах "
        "и показываю ближайшие неоплаченные счета.\nСписок команд: /help"
    )


@dp.message(Command("help"))
async def help_(message: Message):
    await message.answer(
        "/start приветствие\n"
        "/help эта справка\n"
        "/id показать ID этого чата (для CHAT_ID в .env)\n"
        "/payments ближайшие неоплаченные платежи"
    )


@dp.message(Command("id"))
async def chat_id(message: Message):
    await message.answer(f"ID чата: <code>{message.chat.id}</code>")


async def fetch_upcoming_payments() -> list[dict]:
    # TODO: запрос к API, когда Ваня его подготовит.
    raise NotImplementedError


@dp.message(Command("payments"))
async def payments(message: Message):
    try:
        items = await fetch_upcoming_payments()
    except NotImplementedError:
        await message.answer("Список платежей пока недоступен.")
        return
    if not items:
        await message.answer("Неоплаченных платежей нет.")
        return
    e = lambda v: html.escape(str(v), quote=False)
    lines = [f"• {e(p['title'])}: {e(p['amount'])} {e(p['currency'])}, до {e(p['due_date'])}"
             for p in items]
    await message.answer("<b>Ближайшие платежи</b>\n" + "\n".join(lines))


async def main():
    bot = Bot(os.environ["BOT_TOKEN"],
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())