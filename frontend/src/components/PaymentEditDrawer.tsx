import { useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { Currency, PaymentDetailsUpdateRequest, Periodicity } from '../types/api'
import { dateLabel } from '../lib/format'
import { normalizeRecurringAmount } from '../lib/recurring-inputs'
import { SelectField } from './SelectField'
import { PaymentSchedule } from './PaymentSchedule'
import { Drawer, ErrorNotice } from './UI'

interface PaymentEditTarget {
  id: string; title: string; amount: string; currency: Currency; kind: 'period' | 'recurring'
  dueDate?: string; effectiveFrom?: string; periodicity?: Periodicity
  status?: 'paid' | 'unpaid'; recurring_payment_is_active?: boolean
}

export function PaymentEditDrawer({ target, onSave, onSaved, onClose }: {
  target: PaymentEditTarget; onSave: (values: PaymentDetailsUpdateRequest) => Promise<void>; onSaved: () => void; onClose: (refresh?: boolean) => void
}) {
  const id = useId()
  const form = useRef<HTMLFormElement>(null)
  const guard = useRef(false)
  const [title, setTitle] = useState(target.title)
  const [amount, setAmount] = useState(target.amount.replace('.', ','))
  const [currency, setCurrency] = useState(target.currency)
  const [periodicity, setPeriodicity] = useState(target.periodicity || 'monthly')
  const [fields, setFields] = useState<Record<string, string>>({})
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const normalized = normalizeRecurringAmount(amount)
  const moneyChanged = normalized !== target.amount || currency !== target.currency
  const converting = target.periodicity === 'once' && periodicity === 'monthly'
  const unchanged = title.trim() === target.title && !moneyChanged && !converting
  const disabled = busy || uncertain
  const paid = target.status === 'paid'

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (guard.current || disabled || unchanged) return
    const next: Record<string, string> = {}
    if (!title.trim() || Array.from(title.trim()).length > 200) next.title = 'Введите название от 1 до 200 символов.'
    if (!normalized) next.amount = 'Введите сумму от 0,01 до 999999999999,99, не более двух знаков после запятой.'
    if (!['RUB', 'USD', 'EUR'].includes(currency)) next.currency = 'Выберите RUB, USD или EUR.'
    setFields(next); setError(null)
    if (Object.keys(next).length || !normalized) {
      requestAnimationFrame(() => form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus())
      return
    }
    guard.current = true; setBusy(true)
    try {
      await onSave({ title: title.trim(), ...(!paid && moneyChanged ? { amount: normalized, currency } : {}), ...(converting ? { periodicity: 'monthly' as const } : {}) })
      onSaved()
    } catch (reason) {
      setError(reason)
      if (reason instanceof ApiError) {
        setFields(Object.fromEntries(reason.details.map(detail => [detail.field.replace(/^body\./, ''), detail.message])))
        setUncertain(reason.status === 0 || reason.status >= 500 || reason.code === 'INVALID_RESPONSE')
      }
    } finally { guard.current = false; setBusy(false) }
  }

  return <Drawer title="Редактировать платёж" subtitle={target.kind === 'recurring' ? 'Название и условия регулярного платежа.' : target.dueDate ? `Период со сроком ${dateLabel(target.dueDate)}.` : undefined} canClose={!busy} onClose={() => onClose(uncertain)}>
    <form ref={form} className="form-grid" onSubmit={submit} noValidate aria-busy={busy}>
      <div className="field"><label htmlFor={`${id}-title`}>Название платежа</label><input id={`${id}-title`} name="title" value={title} onChange={event => setTitle(event.target.value)} required disabled={disabled} aria-invalid={Boolean(fields.title)} aria-describedby={`${id}-title-hint`}/><small id={`${id}-title-hint`} className={fields.title ? 'field-error' : undefined} role={fields.title ? 'alert' : undefined}>{fields.title || (target.periodicity === 'once' ? 'Название будет видно в списке, истории и напоминаниях.' : 'Название общее для всех периодов этого платежа.')}</small></div>
      <div className="form-row"><div className="field"><label htmlFor={`${id}-amount`}>Сумма</label><input id={`${id}-amount`} name="amount" inputMode="decimal" autoComplete="off" value={amount} onChange={event => setAmount(event.target.value)} required disabled={disabled || paid} aria-invalid={Boolean(fields.amount)} aria-describedby={fields.amount ? `${id}-amount-error` : undefined}/>{fields.amount && <span className="field-error" role="alert" id={`${id}-amount-error`}>{fields.amount}</span>}</div>
        <div className="field"><label htmlFor={`${id}-currency`}>Валюта</label><SelectField id={`${id}-currency`} value={currency} options={['RUB', 'USD', 'EUR'].map(value => ({ value, label: value }))} onChange={value => setCurrency(value as Currency)} disabled={disabled || paid} aria-invalid={Boolean(fields.currency)} aria-describedby={fields.currency ? `${id}-currency-error` : undefined}/>{fields.currency && <span className="field-error" role="alert" id={`${id}-currency-error`}>{fields.currency}</span>}</div></div>
      <p className="payment-edit-scope">{paid ? 'Сумма оплаченного периода зафиксирована. Для её исправления сначала отмените отметку оплаты в карточке платежа.' : target.kind === 'recurring' ? `Сумма и валюта изменятся с ${dateLabel(target.effectiveFrom || null)}. Оплаченные, более ранние и индивидуально настроенные периоды сохранят свои суммы.` : converting ? 'Эта сумма будет использоваться для текущего платежа и новых ежемесячных периодов.' : 'Сумма и валюта изменятся только у этого периода.'} Автоматического пересчёта валют нет.</p>
      {target.kind === 'period' && target.periodicity === 'once' && target.recurring_payment_is_active && <>
        <PaymentSchedule value={periodicity} onChange={setPeriodicity} dueDate={target.dueDate || ''} disabled={disabled}/>
        {converting && <p className="notice" role="status">Платёж будет повторяться ежемесячно от {dateLabel(target.dueDate || null)}. Пропущенные месяцы тоже появятся в обязательствах. Текущая отметка оплаты и чек сохранятся.</p>}
      </>}
      {error != null && <ErrorNotice error={error}/>}
      {uncertain && <p className="notice" role="alert">Изменения могли сохраниться. Закройте панель и проверьте данные перед повторной попыткой.</p>}
      <div className="form-actions"><button className="btn btn-secondary" type="button" data-drawer-close disabled={busy}>{uncertain ? 'Закрыть и проверить' : 'Отмена'}</button><button className="btn btn-primary" type="submit" disabled={disabled || unchanged}>{busy ? 'Сохраняем…' : 'Сохранить изменения'}</button></div>
    </form>
  </Drawer>
}
