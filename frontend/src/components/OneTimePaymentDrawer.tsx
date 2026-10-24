import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import type { Currency } from '../types/api'
import { normalizeRecurringAmount, isCalendarDate } from '../lib/recurring-inputs'
import { Drawer, ErrorNotice } from './UI'
import { SelectField } from './SelectField'
import { DatePicker } from './DatePicker'

export function OneTimePaymentDrawer({ today, onClose, onCreated }: { today: string; onClose: () => void; onCreated: () => void }) {
  const [title, setTitle] = useState('')
  const [amount, setAmount] = useState('')
  const [currency, setCurrency] = useState<Currency>('RUB')
  const [dueDate, setDueDate] = useState(today)
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
    if (!title.trim() || Array.from(title.trim()).length > 200) next.title = 'Название от 1 до 200 символов.'
    if (!normalized) next.amount = 'Введите сумму от 0,01 до 999999999999,99.'
    if (!isCalendarDate(dueDate)) next.due_date = 'Выберите существующую дату.'
    setFields(next); setError(null)
    if (Object.keys(next).length || !normalized) return
    guard.current = true; setBusy(true)
    try { await api.createOneTimePayment({ title: title.trim(), amount: normalized, currency, due_date: dueDate }); onCreated() }
    catch (reason) { setError(reason); if (reason instanceof ApiError) { setFields(Object.fromEntries(reason.details.map(detail => [detail.field,detail.message]))); setUncertain(reason.status === 0 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE') } }
    finally { guard.current = false; setBusy(false) }
  }
  const disabled = busy || uncertain
  return <Drawer title="Новый разовый платёж" subtitle="Один срок оплаты без ежемесячного повторения." canClose={!busy} onClose={onClose}><form className="form-grid" onSubmit={submit} noValidate>
    <label className="field"><span>Название</span><input value={title} onChange={event => setTitle(event.target.value)} disabled={disabled} aria-invalid={Boolean(fields.title)} aria-describedby={fields.title ? 'once-title-error' : undefined}/>{fields.title && <span className="field-error" id="once-title-error">{fields.title}</span>}</label>
    <div className="form-row"><label className="field"><span>Сумма</span><input inputMode="decimal" value={amount} onChange={event => setAmount(event.target.value)} placeholder="45000 или 45000,50" disabled={disabled} aria-invalid={Boolean(fields.amount)} aria-describedby={fields.amount ? 'once-amount-error' : undefined}/>{fields.amount && <span className="field-error" id="once-amount-error">{fields.amount}</span>}</label><div className="field"><label htmlFor="once-currency">Валюта</label><SelectField id="once-currency" value={currency} options={['RUB','USD','EUR'].map(value => ({value,label:value}))} onChange={value => setCurrency(value as Currency)} disabled={disabled}/></div></div>
    <div className="field"><label htmlFor="once-date">Срок оплаты</label><DatePicker id="once-date" today={today} value={dueDate} onChange={setDueDate} disabled={disabled} aria-invalid={Boolean(fields.due_date)} aria-describedby={fields.due_date ? 'once-date-error' : undefined}/>{fields.due_date && <span className="field-error" id="once-date-error">{fields.due_date}</span>}</div>
    {error != null && <ErrorNotice error={error}/>}{uncertain && <p className="notice" role="status">Платёж мог сохраниться. Закройте панель и проверьте список перед повторным созданием.</p>}
    <div className="form-actions"><button type="button" data-drawer-close className="btn btn-secondary" onClick={onClose} disabled={busy}>{uncertain ? 'Проверить список' : 'Отмена'}</button><button type="submit" className="btn btn-primary" disabled={disabled}>{busy ? 'Создаём…' : 'Добавить платёж'}</button></div>
  </form></Drawer>
}
