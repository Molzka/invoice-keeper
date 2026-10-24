"""Run the actual API; redirect only external MFA Telegram HTTP to a local collector."""

import uvicorn
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from app.delivery import mfa_telegram


def local_session(**kwargs):
    return AiohttpSession(api=TelegramAPIServer.from_base("http://access-fixture:8082"), **kwargs)


mfa_telegram.AiohttpSession = local_session
uvicorn.run("app.main:app", host="0.0.0.0", port=8000, access_log=False)
