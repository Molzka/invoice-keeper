import type { Currency, PaymentOccurrence } from '../types/api'

const symbols: Record<Currency, string> = { RUB: '₽', USD: '$', EUR: '€' }
export function money(value: string, currency: Currency): string {
  const [integer, fraction = '00'] = value.split('.')
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0')
  return `${grouped}${fraction === '00' ? '' : ',' + fraction}\u00a0${symbols[currency]}`
}
export function dateLabel(value: string | null): string {
  if (!value) return '—'
  const [year, month, day] = value.split('-')
  return `${day}.${month}.${year}`
}
export function monthRange(month: string) {
  const [year, index] = month.split('-').map(Number)
  const end = new Date(Date.UTC(year, index, 0)).getUTCDate()
  return { date_from: `${month}-01`, date_to: `${month}-${String(end).padStart(2, '0')}` }
}
export function monthLabel(month: string): string {
  const [year, index] = month.split('-').map(Number)
  return new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${String(year).padStart(4, '0')}-${String(index).padStart(2, '0')}-01T12:00:00Z`)).replace(' г.', '')
}
export function statusInfo(item: PaymentOccurrence) {
  if (item.status === 'paid' && item.paid_late) return { text: 'Оплачено с опозданием', className: 'status-warning' }
  if (item.status === 'paid') return { text: 'Оплачено', className: 'status-success' }
  if (item.is_overdue) return { text: 'Просрочено', className: 'status-danger' }
  return { text: 'Не оплачено', className: 'status-neutral' }
}
