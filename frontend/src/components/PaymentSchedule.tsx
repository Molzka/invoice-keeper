import { useId, useRef } from 'react'
import type { Periodicity, RecurringPeriodicity } from '../types/api'
import { dateLabel } from '../lib/format'
import { previewRecurringDueDates } from '../lib/recurring-inputs'
import { SelectField } from './SelectField'

export function PaymentSchedule({ value, onChange, dueDate, disabled = false, interval = '1', onIntervalChange, intervalError, periodicityError }: { value: Periodicity; onChange: (value: Periodicity) => void; dueDate: string; disabled?: boolean; interval?: string; onIntervalChange?: (value: string) => void; intervalError?: string; periodicityError?: string }) {
  const id = useId()
  const lastRecurring = useRef<RecurringPeriodicity>(value === 'once' ? 'monthly' : value)
  const dates = previewRecurringDueDates(dueDate, value, Number(interval))
  return <fieldset className="payment-frequency" disabled={disabled} aria-describedby={`${id}-hint`}>
    <legend>Повторение</legend>
    <div className="payment-frequency-options">{([['once', 'Разовый', 'Один платёж'], ['recurring', onIntervalChange ? 'Регулярный' : 'Ежемесячный', onIntervalChange ? 'По выбранному расписанию' : 'Повторять каждый месяц']] as const).map(([key, title, hint]) => <label key={key}>
      <input type="radio" name={`frequency-${id}`} value={key} checked={key === 'once' ? value === 'once' : value !== 'once'} onChange={() => onChange(key === 'once' ? 'once' : lastRecurring.current)}/>
      <span><strong>{title}</strong><small>{hint}</small></span>
    </label>)}</div>
    {value !== 'once' && onIntervalChange && <div className="form-row recurring-frequency-fields">
      <div className="field"><label htmlFor={`${id}-interval`}>Повторять раз в</label><input id={`${id}-interval`} name="recurrence_interval" type="number" min="1" max="365" step="1" value={interval} onChange={event => onIntervalChange(event.target.value)} required disabled={disabled} aria-invalid={Boolean(intervalError)} aria-describedby={intervalError ? `${id}-interval-error` : undefined}/>{intervalError && <span id={`${id}-interval-error`} className="field-error" role="alert">{intervalError}</span>}</div>
      <div className="field"><label htmlFor={`${id}-periodicity`}>Периодичность</label><SelectField id={`${id}-periodicity`} value={value} onChange={next => { lastRecurring.current = next as RecurringPeriodicity; onChange(lastRecurring.current) }} options={[{ value: 'daily', label: 'Дни' }, { value: 'weekly', label: 'Недели' }, { value: 'monthly', label: 'Месяцы' }, { value: 'yearly', label: 'Годы' }]} disabled={disabled} aria-invalid={Boolean(periodicityError)} aria-describedby={periodicityError ? `${id}-periodicity-error` : undefined}/>{periodicityError && <span id={`${id}-periodicity-error`} className="field-error" role="alert">{periodicityError}</span>}</div>
    </div>}
    <p id={`${id}-hint`} className="field-hint">{value === 'once' ? 'После этого срока новых платежей не будет.' : value === 'monthly' || value === 'yearly' ? 'Если нужного числа нет, сроком станет последний день месяца.' : 'Платежи будут повторяться с выбранным интервалом от первого срока.'}</p>
    {value !== 'once' && dates.length > 0 && <div className="payment-schedule-preview" aria-live="polite"><span>Первые сроки</span><ol>{dates.map(date => <li key={date}><time dateTime={date}>{dateLabel(date)}</time></li>)}</ol></div>}
  </fieldset>
}
