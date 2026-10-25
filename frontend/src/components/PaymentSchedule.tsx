import { useId } from 'react'
import { dateLabel } from '../lib/format'
import { previewMonthlyDueDates } from '../lib/recurring-inputs'

export function PaymentSchedule({ value, onChange, dueDate, disabled = false }: { value: 'once' | 'monthly'; onChange: (value: 'once' | 'monthly') => void; dueDate: string; disabled?: boolean }) {
  const id = useId()
  const dates = previewMonthlyDueDates(dueDate)
  return <fieldset className="payment-frequency" disabled={disabled} aria-describedby={`${id}-hint`}>
    <legend>Повторение</legend>
    <div className="payment-frequency-options">{([['once', 'Разовый', 'Один платёж'], ['monthly', 'Ежемесячный', 'Повторять каждый месяц']] as const).map(([key, title, hint]) => <label key={key}>
      <input type="radio" name={`frequency-${id}`} value={key} checked={value === key} onChange={() => onChange(key)}/>
      <span><strong>{title}</strong><small>{hint}</small></span>
    </label>)}</div>
    <p id={`${id}-hint`} className="field-hint">{value === 'once' ? 'После этого срока новых платежей не будет.' : 'В тот же день каждого месяца. Если такого числа нет — в последний день месяца.'}</p>
    {value === 'monthly' && dates.length > 0 && <div className="payment-schedule-preview" aria-live="polite"><span>Первые сроки</span><ol>{dates.map(date => <li key={date}><time dateTime={date}>{dateLabel(date)}</time></li>)}</ol></div>}
  </fieldset>
}
