"""Telegram-интерфейс Invoice Keeper. Данные счетов получаются через HTTP API; локальная БД не используется."""
import asyncio, contextlib, html, json, logging, os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from dotenv import load_dotenv
from api import ApiDataError, ApiNotConfigured, ApiUnavailable, fetch_payments

BASE = Path(__file__).parent
T = json.loads((BASE / 'texts.json').read_text(encoding='utf-8'))
load_dotenv(BASE / '.env', override=True)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('bot')
PAGE_SIZE = 5

def allowed_chat():
    try: return int(os.getenv('CHAT_ID', '').strip())
    except (ValueError, TypeError): return None

def money(amount, currency):
    try: value = Decimal(str(amount).replace(' ', '').replace('\u00a0','').replace(',', '.')).quantize(Decimal('0.01'), ROUND_HALF_UP)
    except InvalidOperation as e: raise ValueError('Некорректная сумма') from e
    return f"{value:,.2f}".replace(',', ' ').replace('.', ',') + f' {currency}'

def date_text(value):
    if isinstance(value, datetime): value = value.date()
    if isinstance(value, date): return value.strftime('%d.%m.%Y')
    for fmt in ('%Y-%m-%d', '%d.%m.%Y'):
        try: return datetime.strptime(str(value).strip(), fmt).strftime('%d.%m.%Y')
        except ValueError: pass
    raise ValueError('Некорректная дата')

def status(payment, today=None):
    today = today or date.today()
    due = datetime.strptime(date_text(payment['due_date']), '%d.%m.%Y').date()
    return 'Просрочен' if due < today else ('К оплате сегодня' if due == today else 'Ожидает оплаты')

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📋 Все счета', callback_data='list:upcoming:0'), InlineKeyboardButton(text='⚠️ Просроченные', callback_data='list:overdue:0')],
        [InlineKeyboardButton(text='📅 На ближайшие 7 дней', callback_data='list:upcoming:0'), InlineKeyboardButton(text='📊 Сводка', callback_data='summary')],
        [InlineKeyboardButton(text='❔ Помощь', callback_data='help')],
    ])

def payment_card(payment, index=1):
    title = html.escape(str(payment['title']), quote=False)
    amount = html.escape(money(payment['amount'], payment['currency']), quote=False)
    due = html.escape(date_text(payment['due_date']), quote=False)
    return f"<b>{index}. {title}</b>\nСумма: {amount}\nСрок: {due}\nСтатус: {html.escape(status(payment))}"

def summary_text(items):
    overdue = [p for p in items if status(p) == 'Просрочен']
    total = sum((Decimal(str(p['amount']).replace(',', '.')) for p in items), Decimal('0'))
    currencies = {p['currency'] for p in items}
    total_text = money(total, next(iter(currencies))) if len(currencies) == 1 else 'суммы в разных валютах'
    return f'<b>Финансовая сводка</b>\nВсего счетов: {len(items)}\nПросрочено: {len(overdue)}\nСумма счетов: {html.escape(total_text)}'

async def fetch(kind): return await fetch_payments(kind)

async def reminder_loop(bot, chat_id):
    # Дедупликация в памяти: после перезапуска ключи сбрасываются. Постоянное хранение не используется.
    sent = set()
    while True:
        try:
            items = await fetch('upcoming')
            items += await fetch('overdue')
            today = date.today()
            for p in items:
                due = datetime.strptime(date_text(p['due_date']), '%d.%m.%Y').date()
                days = (due - today).days
                if days > int(os.getenv('REMIND_DAYS', '3')):
                    continue
                key = (str(p['title']), str(p['due_date']), str(p['amount']), str(p['currency']))
                if key in sent: continue
                label = 'Просрочен' if days < 0 else ('Срок оплаты сегодня' if days == 0 else f'До срока оплаты {days} дн.')
                msg = f"<b>Напоминание об оплате</b>\n{html.escape(str(p['title']))}\nСумма: {html.escape(money(p['amount'], p['currency']))}\nСрок: {html.escape(date_text(p['due_date']))}\nСтатус: {label}"
                await bot.send_message(chat_id, msg)
                sent.add(key)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning('Цикл напоминаний: %s', type(exc).__name__)
        await asyncio.sleep(max(5, int(os.getenv('REMINDER_CHECK_MINUTES', '30'))) * 60)
async def answer_list(message, kind, page):
    try: items = await fetch(kind)
    except ApiNotConfigured: return await message.answer('Источник счетов пока не настроен. Попробуйте позже.')
    except (ApiUnavailable, ApiDataError, asyncio.TimeoutError, aiohttp.ClientError) as e:
        log.warning('Не удалось получить счета: %s', type(e).__name__)
        return await message.answer('Не удалось загрузить счета. Попробуйте позже.')
    if kind == 'overdue': items = [p for p in items if status(p) == 'Просрочен']
    if not items: return await message.answer('Счетов в этом разделе нет.', reply_markup=main_keyboard())
    pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
    page = max(0, min(page, pages - 1)); chunk = items[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
    text = f'<b>{"Просроченные счета" if kind == "overdue" else "Счета на ближайшие 7 дней"}</b> · {page+1}/{pages}\n\n'
    text += '\n\n'.join(payment_card(p, page*PAGE_SIZE+i+1) for i,p in enumerate(chunk))
    rows = [[InlineKeyboardButton(text='Открыть карточку ' + str(page*PAGE_SIZE+i+1), callback_data=f'card:{kind}:{page*PAGE_SIZE+i}') ] for i,p in enumerate(chunk)]
    nav=[]
    if page: nav.append(InlineKeyboardButton(text='⬅️', callback_data=f'list:{kind}:{page-1}'))
    if page < pages-1: nav.append(InlineKeyboardButton(text='➡️', callback_data=f'list:{kind}:{page+1}'))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(text='🏠 Меню', callback_data='menu')])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

async def main():
    token = os.getenv('BOT_TOKEN', '').strip()
    if not token: raise SystemExit('BOT_TOKEN не задан в .env')
    chat_id = allowed_chat(); router = Router(); public = Router()
    def permitted(m): return chat_id is not None and m.chat.id == chat_id
    @public.message(CommandStart())
    async def start(m: Message): await m.answer('<b>Invoice Keeper</b>\nКонтроль счетов и сроков оплаты.', reply_markup=main_keyboard())
    @public.message(Command('help'))
    async def help_cmd(m: Message): await m.answer('Команды: /start, /payments, /overdue, /summary. Используйте кнопки меню.')
    @public.message(Command('payments'))
    async def payments(m: Message):
        if not permitted(m): return await m.answer('Эта команда недоступна в данном чате.')
        await answer_list(m, 'upcoming', 0)
    @public.message(Command('overdue'))
    async def overdue(m: Message):
        if not permitted(m): return await m.answer('Эта команда недоступна в данном чате.')
        await answer_list(m, 'overdue', 0)
    @public.message(Command('summary'))
    async def summary(m: Message):
        if not permitted(m): return await m.answer('Эта команда недоступна в данном чате.')
        try: items = await fetch('upcoming')
        except (ApiNotConfigured, ApiUnavailable, ApiDataError, asyncio.TimeoutError, aiohttp.ClientError): return await m.answer('Не удалось загрузить сводку. Проверьте подключение источника счетов.')
        await m.answer(summary_text(items), reply_markup=main_keyboard())
    @public.callback_query(F.data == 'menu')
    async def menu(c: CallbackQuery): await c.message.answer('Главное меню', reply_markup=main_keyboard()); await c.answer()
    @public.callback_query(F.data == 'help')
    async def help_cb(c: CallbackQuery): await c.message.answer('Выберите «Все счета», «Просроченные» или «Сводка».'); await c.answer()
    @public.callback_query(F.data.startswith('list:'))
    async def list_cb(c: CallbackQuery):
        if not permitted(c.message): return await c.answer('Недоступно в этом чате', show_alert=True)
        _,kind,page=c.data.split(':'); await answer_list(c.message,kind,int(page)); await c.answer()
    @public.callback_query(F.data == 'summary')
    async def summary_cb(c: CallbackQuery):
        if not permitted(c.message): return await c.answer('Недоступно в этом чате', show_alert=True)
        try: items=await fetch('upcoming'); await c.message.answer(summary_text(items), reply_markup=main_keyboard())
        except (ApiNotConfigured, ApiUnavailable, ApiDataError, asyncio.TimeoutError, aiohttp.ClientError): await c.message.answer('Не удалось загрузить сводку.')
        await c.answer()
    @public.callback_query(F.data.startswith('card:'))
    async def card_cb(c: CallbackQuery):
        if not permitted(c.message): return await c.answer('Недоступно в этом чате', show_alert=True)
        _,kind,raw=c.data.split(':'); idx=int(raw)
        try: items=await fetch(kind)
        except (ApiNotConfigured, ApiUnavailable, ApiDataError, asyncio.TimeoutError, aiohttp.ClientError): await c.answer('Не удалось загрузить счёт',show_alert=True); return
        if kind=='overdue': items=[p for p in items if status(p)=='Просрочен']
        if idx < 0 or idx >= len(items): await c.answer('Счёт больше недоступен',show_alert=True); return
        await c.message.answer('<b>Карточка счёта</b>\n\n'+payment_card(items[idx],idx+1), reply_markup=main_keyboard()); await c.answer()
    dp=Dispatcher(); dp.include_router(public)
    bot=Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        with contextlib.suppress(TelegramAPIError): await bot.set_my_commands([BotCommand(command='start',description='Главное меню'),BotCommand(command='payments',description='Счета на 7 дней'),BotCommand(command='overdue',description='Просроченные счета'),BotCommand(command='summary',description='Финансовая сводка'),BotCommand(command='help',description='Помощь')])
        reminder_task = asyncio.create_task(reminder_loop(bot, chat_id)) if chat_id is not None else None
        try: await dp.start_polling(bot)
        finally:
            if reminder_task:
                reminder_task.cancel()
                with contextlib.suppress(asyncio.CancelledError): await reminder_task
    finally: await bot.session.close()
if __name__=='__main__': asyncio.run(main())
