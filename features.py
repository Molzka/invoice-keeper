"""Pure functions for invoice display; no Telegram or database dependency."""
import html
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

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
