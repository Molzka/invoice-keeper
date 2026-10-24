/** One business clock shared by the demo UI and its replaceable mock server. */
export const APP_TIMEZONE = 'Europe/Moscow'
export const DEMO_TODAY = '2026-10-23'
export const DEMO_NOW_ISO = `${DEMO_TODAY}T09:30:00.000Z`
const monthNames = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
const [demoYear, demoMonth, demoDay] = DEMO_TODAY.split('-').map(Number)
export const DEMO_DATE_LABEL = `${demoDay} ${monthNames[demoMonth - 1]} ${demoYear}`

export function businessToday(mode: 'mock' | 'real', now?: Date, timezone?: string): string {
  if (mode === 'mock') return DEMO_TODAY
  if (!timezone) throw new RangeError('The authenticated server timezone is required')
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now ?? new Date())
  const value = (type: string) => parts.find(part => part.type === type)?.value ?? ''
  return `${value('year')}-${value('month')}-${value('day')}`
}

export function businessNowIso(mode: 'mock' | 'real', now?: Date): string {
  return mode === 'mock' ? DEMO_NOW_ISO : (now ?? new Date()).toISOString()
}

/** Calendar-only arithmetic: no browser timezone or UTC-midnight conversion. */
export function calendarMonthDate(reference: string, anchor: number, offset = 0): string {
  const [referenceYear, referenceMonth] = reference.split('-').map(Number)
  const absoluteMonth = referenceYear * 12 + referenceMonth - 1 + offset
  const year = Math.floor(absoluteMonth / 12), month = absoluteMonth % 12 + 1
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(Math.min(anchor, days)).padStart(2, '0')}`
}

export function calendarMonthBounds(reference: string) {
  return { date_from: calendarMonthDate(reference, 1), date_to: calendarMonthDate(reference, 31) }
}

export function shiftCalendarDays(reference: string, days: number): string {
  const value = new Date(`${reference}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate() + days)
  return value.toISOString().slice(0, 10)
}
