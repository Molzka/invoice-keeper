"""Personal security codes; independent of the financial reminder destination."""

import re

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from app.core.config import Settings

_PURPOSES = {
    "login": "Подтверждение входа в Invoice Keeper",
    "reauth": "Изменение настроек безопасности Invoice Keeper",
    "link": "Привязка Telegram к Invoice Keeper",
}


async def send_mfa_code(settings: Settings, chat_id: int, code: str, purpose: str) -> None:
    if type(chat_id) is not int or chat_id <= 0:
        raise ValueError("A personal Telegram chat is required")
    if not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None:
        raise ValueError("Invalid security code")
    if purpose not in _PURPOSES or settings.bot_token is None:
        raise ValueError("Personal Telegram delivery is not configured")
    async with Bot(
        token=settings.bot_token.get_secret_value(), session=AiohttpSession(timeout=10)
    ) as bot:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"<b>{_PURPOSES[purpose]}</b>\n\n"
                f"Код: <code>{code}</code>\n"
                "Действует 5 минут. Введите его только в открытой вами веб-панели.\n"
                "Никому не сообщайте код. Если вы не запрашивали его, проигнорируйте сообщение."
            ),
            parse_mode="HTML",
            protect_content=True,
        )
