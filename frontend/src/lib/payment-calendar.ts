import type { OccurrenceFilters, Page, PaymentOccurrence } from '../types/api'

export type CalendarStatus = 'all' | 'unpaid' | 'overdue' | 'paid'
export interface CalendarRoute { month: string; day: string; currency: '' | 'RUB' | 'USD' | 'EUR'; status: CalendarStatus }
const currencies = ['', 'RUB', 'USD', 'EUR']
const statuses = ['all', 'unpaid', 'overdue', 'paid']
export function calendarMonthDays(month: string): number {
  const [year, number] = month.split('-').map(Number)
  if (!/^\d{4}-\d{2}$/.test(month) || year < 1 || number < 1 || number > 12) throw new RangeError('Некорректный месяц')
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][number - 1]
}
export function validCalendarDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  try { return +value.slice(-2) >= 1 && +value.slice(-2) <= calendarMonthDays(value.slice(0, 7)) } catch { return false }
}
export function calendarMonthRange(month: string) { return { date_from: `${month}-01`, date_to: `${month}-${calendarMonthDays(month)}` } }
export function moveCalendarMonth(month: string, delta: -1 | 1): string | null {
  calendarMonthDays(month)
  const [year, number] = month.split('-').map(Number)
  const absolute = (year - 1) * 12 + number - 1 + delta
  if (absolute < 0 || absolute >= 9999 * 12) return null
  return `${String(Math.floor(absolute / 12) + 1).padStart(4, '0')}-${String(absolute % 12 + 1).padStart(2, '0')}`
}
export function calendarCells(month: string): (string | null)[] {
  const days = calendarMonthDays(month)
  const year = +month.slice(0, 4), number = +month.slice(5, 7)
  // Gregorian day counts: 0001-01-01 was Monday. No browser time zone participates.
  const previousYear = year - 1
  const beforeYear = previousYear * 365 + Math.floor(previousYear / 4) - Math.floor(previousYear / 100) + Math.floor(previousYear / 400)
  let beforeMonth = 0
  for (let index = 1; index < number; index++) beforeMonth += calendarMonthDays(`${String(year).padStart(4, '0')}-${String(index).padStart(2, '0')}`)
  const offset = (beforeYear + beforeMonth) % 7
  const result: (string | null)[] = Array.from({ length: offset }, () => null)
  for (let day = 1; day <= days; day++) result.push(`${month}-${String(day).padStart(2, '0')}`)
  while (result.length % 7) result.push(null)
  return result
}
export function readCalendarRoute(hash: string, today: string): CalendarRoute {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  let month = params.get('month') || today.slice(0, 7)
  try { calendarMonthDays(month) } catch { month = today.slice(0, 7) }
  const value = params.get('day') || (month === today.slice(0, 7) ? today : `${month}-01`)
  const day = validCalendarDay(value) && value.startsWith(month + '-') ? value : `${month}-01`
  const currency = params.get('currency') || '', status = params.get('status') || 'all'
  return { month, day, currency: currencies.includes(currency) ? currency as CalendarRoute['currency'] : '', status: statuses.includes(status) ? status as CalendarStatus : 'all' }
}
export function calendarHash(route: CalendarRoute): string {
  const params = new URLSearchParams({ month: route.month, day: route.day })
  if (route.currency) params.set('currency', route.currency)
  params.set('status', route.status)
  return '#calendar?' + params.toString()
}
export function calendarOccurrenceFilters(route: CalendarRoute): OccurrenceFilters {
  return { ...calendarMonthRange(route.month), ...(route.currency ? { currency: route.currency } : {}), ...(route.status === 'all' ? {} : { status: route.status === 'paid' ? 'paid' : 'unpaid' }), ...(route.status === 'overdue' ? { is_overdue: true } : {}) }
}
/** All pages are required. Failed/inconsistent pages must never masquerade as an empty day. */
export async function loadCalendarOccurrences(filters: OccurrenceFilters, load: (filters: OccurrenceFilters) => Promise<Page<PaymentOccurrence>>, active: () => boolean = () => true): Promise<PaymentOccurrence[]> {
  const items: PaymentOccurrence[] = [], ids = new Set<string>()
  let expectedTotal: number | null = null
  while (active()) {
    const page = await load({ ...filters, limit: 100, offset: items.length })
    if (!active()) throw new Error('Загрузка отменена')
    if (!Array.isArray(page.items) || !Number.isSafeInteger(page.total) || page.total < 0 || page.offset !== items.length || page.items.length > 100 || (expectedTotal !== null && expectedTotal !== page.total)) throw new Error('Список платежей изменился во время загрузки. Обновите календарь.')
    expectedTotal = page.total
    if (page.items.length === 0 && items.length < expectedTotal) throw new Error('Сервер вернул неполный список платежей. Обновите календарь.')
    for (const item of page.items) {
      if (ids.has(item.id)) throw new Error('Список платежей изменился во время загрузки. Обновите календарь.')
      ids.add(item.id); items.push(item)
    }
    if (items.length > expectedTotal) throw new Error('Сервер вернул несогласованный список платежей. Обновите календарь.')
    if (items.length === expectedTotal) return items.sort((a, b) => a.due_date.localeCompare(b.due_date) || a.title.localeCompare(b.title, 'ru') || a.id.localeCompare(b.id))
  }
  throw new Error('Загрузка отменена')
}
