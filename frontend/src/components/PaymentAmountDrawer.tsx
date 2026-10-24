import { useEffect, useId, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertCircle, Check, Coins, Info, ShieldCheck } from './BrandIcons'
import { ApiError } from '../api/client'
import type { Currency } from '../types/api'
import { dateLabel, money } from '../lib/format'
import { isCalendarDate, normalizeRecurringAmount } from '../lib/recurring-inputs'
import { SelectField } from './SelectField'
import { Drawer, ErrorNotice } from './UI'

export interface PaymentAmountTarget {
  id: string
  title: string
  amount: string
  currency: Currency
  kind: 'period' | 'recurring'
  dueDate?: string
  effectiveFrom?: string
}
interface Props {
  target: PaymentAmountTarget
  available: boolean
  onSave: (values: { amount: string; currency: Currency }) => Promise<void>
  onSaved: () => void
  onClose: () => void
}
type FieldErrors = Partial<Record<'amount' | 'currency', string>>
const currencies: Currency[] = ['RUB', 'USD', 'EUR']
const currencyOptions = [
  { value: 'RUB', label: 'RUB', description: 'Российский рубль' },
  { value: 'USD', label: 'USD', description: 'Доллар США' },
  { value: 'EUR', label: 'EUR', description: 'Евро' },
]

/** I/O is supplied by the caller so display controls never invent a server capability. */
export function PaymentAmountDrawer({ target, available, onSave, onSaved, onClose }: Props) {
  const id = useId()
  const amountId = `payment-amount-${id}`
  const currencyId = `payment-currency-${id}`
  const [amount, setAmount] = useState(() => target.amount.replace('.', ','))
  const [currency, setCurrency] = useState<Currency>(target.currency)
  const [fields, setFields] = useState<FieldErrors>({})
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const amountInput = useRef<HTMLInputElement>(null)
  const guard = useRef(false)
  const mounted = useRef(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const normalized = normalizeRecurringAmount(amount)
  const originalAmount = normalizeRecurringAmount(target.amount) || target.amount
  const unchanged = normalized === originalAmount && currency === target.currency
  const effectiveReady = target.kind === 'period' || Boolean(target.effectiveFrom && isCalendarDate(target.effectiveFrom))
  const blocked = busy || uncertain || !available || !effectiveReady

  function showFields(next: FieldErrors) {
    setFields(next)
    requestAnimationFrame(() => {
      if (!mounted.current) return
      if (next.amount) amountInput.current?.focus()
      else if (next.currency) document.getElementById(currencyId)?.focus()
    })
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (guard.current || blocked) return
    const normalizedAmount = normalizeRecurringAmount(amount)
    const next: FieldErrors = {}
    if (normalizedAmount === null) next.amount = 'Введите сумму от 0,01 до 999999999999,99, не более двух знаков после запятой или точки.'
    if (!currencies.includes(currency)) next.currency = 'Выберите RUB, USD или EUR.'
    setError(null)
    if (Object.keys(next).length || normalizedAmount === null) { showFields(next); return }
    if (normalizedAmount === originalAmount && currency === target.currency) return
    guard.current = true; setBusy(true); setFields({})
    try {
      // Exact decimal string; this component never retries a mutation automatically.
      await onSave({ amount: normalizedAmount, currency })
      if (mounted.current) onSaved()
    } catch (reason) {
      if (!mounted.current) return
      const apiError = reason instanceof ApiError ? reason : null
      if (apiError?.status === 401) return
      const nextFields: FieldErrors = {}
      for (const detail of apiError?.details || []) {
        const field = detail.field.replace(/^body\./, '')
        if (field === 'amount' || field === 'currency') nextFields[field] = detail.message
      }
      showFields(nextFields)
      const unknownOutcome = apiError?.status === 0 || (apiError !== null && apiError.status >= 500) || apiError?.code === 'INVALID_RESPONSE'
      if (unknownOutcome) setUncertain(true)
      setError(reason)
    } finally { guard.current = false; if (mounted.current) setBusy(false) }
  }

  return <Drawer title="Изменить сумму и валюту" subtitle={target.kind === 'period' ? 'Условия одного периода оплаты.' : 'Новые условия регулярного платежа.'} canClose={!busy} onClose={() => { if (!guard.current) onClose() }}>
    <section className="amount-edit-target" aria-label="Текущие условия платежа">
      <div className="amount-edit-heading"><span className="amount-edit-icon" aria-hidden="true"><Coins size={23}/></span><div><p>{target.kind === 'period' ? 'Отдельный период' : 'Регулярный платёж'}</p><h3>{target.title}</h3></div></div>
      <dl className="amount-edit-current"><div><dt>Сейчас</dt><dd>{money(target.amount, target.currency)}<span>{target.currency}</span></dd></div>{target.kind === 'period' && target.dueDate && <div><dt>Срок оплаты</dt><dd>{dateLabel(target.dueDate)}</dd></div>}</dl>
    </section>
    <div className="notice amount-edit-scope"><ShieldCheck size={20} aria-hidden="true"/><p>{target.kind === 'period' ? 'Изменится сумма и валюта только этого неоплаченного периода. Остальные периоды сохранят свои условия.' : target.effectiveFrom && effectiveReady ? <>Новые условия действуют с <strong>{dateLabel(target.effectiveFrom)}</strong> для неоплаченных периодов со сроком от этой даты. Оплаченная история, более ранние периоды и индивидуальные условия отдельных периодов сохранятся.</> : 'Дата начала новых условий ещё не определена. Обновите данные платежа.'}</p></div>
    {!available && <div className="amount-edit-unavailable" role="status"><Info size={20} aria-hidden="true"/><div><strong>Сервер ещё не поддерживает изменение суммы и валюты</strong><p>Для сохранения требуется подключение API. Текущие условия платежа показаны выше.</p></div></div>}
    <form className="amount-edit-form" onSubmit={submit} noValidate aria-busy={busy}>
      <div className="amount-edit-fields"><div className="field"><label htmlFor={amountId}>Новая сумма</label><input ref={amountInput} id={amountId} name="amount" type="text" inputMode="decimal" autoComplete="off" spellCheck={false} maxLength={32} value={amount} onChange={event => { setAmount(event.target.value); setFields(previous => ({ ...previous, amount: undefined })) }} required disabled={blocked} aria-invalid={Boolean(fields.amount)} aria-describedby={`${amountId}-hint${fields.amount ? ` ${amountId}-error` : ''}`}/><small id={`${amountId}-hint`}>Например: 45000, 45000,50 или 45000.50</small>{fields.amount && <span className="field-error" id={`${amountId}-error`} role="alert">{fields.amount}</span>}</div>
      <div className="field"><label htmlFor={currencyId}>Новая валюта</label><SelectField id={currencyId} name="currency" value={currency} options={currencyOptions} onChange={value => { setCurrency(value as Currency); setFields(previous => ({ ...previous, currency: undefined })) }} required disabled={blocked} aria-invalid={Boolean(fields.currency)} aria-describedby={fields.currency ? `${currencyId}-error` : undefined}/>{fields.currency && <span className="field-error" id={`${currencyId}-error`} role="alert">{fields.currency}</span>}</div></div>
      <p className="amount-edit-currency-hint">Укажите сумму в выбранной валюте. Автоматического пересчёта по курсу нет.</p>
      <div className="amount-edit-preview" data-changed={!unchanged && normalized !== null}><span>После сохранения</span><strong aria-live="polite">{normalized !== null && currencies.includes(currency) ? money(normalized, currency) : 'Укажите корректную сумму'}</strong></div>
      {uncertain ? <div className="amount-edit-uncertain" role="alert"><AlertCircle size={20} aria-hidden="true"/><div><strong>Результат сохранения пока неизвестен</strong><p>Изменение могло сохраниться. Закройте панель и проверьте актуальные данные перед повторной попыткой.</p></div></div> : error ? <ErrorNotice error={error}/> : null}
      <div className="form-actions amount-edit-actions">{uncertain ? <button className="btn btn-primary" type="button" data-drawer-close="">Закрыть и проверить данные</button> : <><button className="btn btn-primary" type="submit" disabled={busy || !available || !effectiveReady || unchanged}>{busy ? <span className="spinner"/> : <Check size={17} aria-hidden="true"/>}{busy ? 'Сохраняем…' : 'Сохранить изменения'}</button><button className="btn btn-secondary" type="button" disabled={busy} data-drawer-close="">Отмена</button></>}</div>
    </form>
  </Drawer>
}
