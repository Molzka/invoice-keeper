import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Currency, Periodicity } from '../types/api'
import { normalizeRecurringAmount, isCalendarDate } from '../lib/recurring-inputs'
import { Drawer, ErrorNotice } from './UI'
import { SelectField } from './SelectField'
import { DatePicker } from './DatePicker'
import { PaymentSchedule } from './PaymentSchedule'

export function CreatePaymentDrawer({ today, initialPeriodicity = 'once', onClose, onCreated }: { today: string; initialPeriodicity?: Periodicity; onClose: () => void; onCreated: (payment: { id: string; title: string; periodicity: Periodicity }) => void }) {
  const [title, setTitle] = useState('')
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState<Currency>('RUB')
  const [dueDate, setDueDate] = useState(today)
  const [periodicity, setPeriodicity] = useState(initialPeriodicity)
  const [interval, setInterval] = useState('1')
  const [fields, setFields] = useState<Record<string,string>>({})
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const guard = useRef(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (guard.current || uncertain) return
    const normalized = normalizeRecurringAmount(amount)
    const next: Record<string,string> = {}
    if (!title.trim() || Array.from(title.trim()).length > 200) next.title = 'Введите название от 1 до 200 символов.'
    if (!normalized) next.amount = 'Введите сумму от 0,01 до 999999999999,99.'
    if (!isCalendarDate(dueDate)) next.due_date = 'Выберите существующую дату.'
    if (!['RUB', 'USD', 'EUR'].includes(currency)) next.currency = 'Выберите RUB, USD или EUR.'
    if (periodicity !== 'once' && (!Number.isInteger(Number(interval)) || Number(interval) < 1 || Number(interval) > 365)) next.recurrence_interval = 'Введите целое число от 1 до 365.'
    setFields(next); setError(null)
    if (Object.keys(next).length || !normalized) { requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus()); return }
    guard.current = true; setBusy(true)
    try {
      const values = { title: title.trim(), amount: normalized, currency }
      if (periodicity !== 'once') {
        const payment = await api.createRecurringPayment({ ...values, first_due_date: dueDate, periodicity, recurrence_interval: Number(interval) })
        onCreated({ id: payment.id, title: payment.title, periodicity })
      } else {
        const item = await api.createOneTimePayment({ ...values, due_date: dueDate })
        onCreated({ id: item.recurring_payment_id, title: item.title, periodicity })
      }
    }
    catch (reason) { setError(reason); if (reason instanceof ApiError) { setFields(Object.fromEntries(reason.details.map(detail => [detail.field.replace(/^body\./, '').replace('first_due_date', 'due_date'),detail.message]))); setUncertain(reason.status === 0 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE') } }
    finally { guard.current = false; setBusy(false) }
  }
  const disabled = busy || uncertain
  return <Drawer title="Новый платёж" subtitle="Укажите, за что платите и нужно ли повторять платёж." canClose={!busy} onClose={onClose}><form className="form-grid" onSubmit={submit} noValidate>
    <div className="field"><label htmlFor="create-title">Название платежа</label><input id="create-title" name="title" required value={title} placeholder="Например, аренда офиса" onChange={event => setTitle(event.target.value)} disabled={disabled} aria-invalid={Boolean(fields.title)} aria-describedby={fields.title ? 'once-title-error' : undefined}/>{fields.title && <span className="field-error" role="alert" id="once-title-error">{fields.title}</span>}</div>
    <div className="form-row"><div className="field"><label htmlFor="create-amount">Сумма</label><input id="create-amount" name="amount" required inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} placeholder="45000 или 45000,50" disabled={disabled} aria-invalid={Boolean(fields.amount)} aria-describedby={fields.amount ? 'once-amount-error' : undefined}/>{fields.amount && <span className="field-error" role="alert" id="once-amount-error">{fields.amount}</span>}</div><div className="field"><label htmlFor="once-currency">Валюта</label><SelectField id="once-currency" value={currency} options={['RUB','USD','EUR'].map(value => ({value,label:value}))} onChange={value => setCurrency(value as Currency)} disabled={disabled} aria-invalid={Boolean(fields.currency)} aria-describedby={fields.currency ? 'once-currency-error' : undefined}/>{fields.currency && <span className="field-error" role="alert" id="once-currency-error">{fields.currency}</span>}</div></div>
    <div className="field"><label htmlFor="once-date">{periodicity !== 'once' ? 'Первый срок оплаты' : 'Срок оплаты'}</label><DatePicker id="once-date" today={today} aria-label={periodicity !== 'once' ? 'Первый срок оплаты' : 'Срок оплаты'} value={dueDate} onChange={setDueDate} disabled={disabled} aria-invalid={Boolean(fields.due_date)} aria-describedby={fields.due_date ? 'once-date-error' : undefined}/>{fields.due_date && <span className="field-error" role="alert" id="once-date-error">{fields.due_date}</span>}</div>
    <PaymentSchedule value={periodicity} onChange={setPeriodicity} dueDate={dueDate} disabled={disabled} interval={interval} onIntervalChange={value => { setInterval(value); setFields(current => ({ ...current, recurrence_interval: '' })) }} intervalError={fields.recurrence_interval} periodicityError={fields.periodicity}/>
    {periodicity !== 'once' && dueDate < today && <p className="notice">Выбрана прошедшая дата. Будут добавлены все обязательства по расписанию от первого срока до текущего месяца.</p>}
    {error != null && <ErrorNotice error={error}/>}{uncertain && <p className="notice" role="status">Платёж мог сохраниться. Закройте панель и проверьте список перед повторным созданием.</p>}
    <div className="form-actions"><button type="button" data-drawer-close className="btn btn-secondary" onClick={onClose} disabled={busy}>{uncertain ? 'Проверить список' : 'Отмена'}</button><button type="submit" className="btn btn-primary" disabled={disabled}>{busy ? 'Создаём…' : 'Добавить платёж'}</button></div>
  </form></Drawer>
}
