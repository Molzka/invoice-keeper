import type { AuditAction, AuditFilters } from '../types/activity'

export const auditActionLabels: Record<AuditAction, string> = {
  'payment.deleted': 'Удалён платёж', 'payment.period_deleted': 'Удалён период платежа',
  'payment.created': 'Создание платежа',
  'payment.stopped': 'Прекращение платежа',
  'payment.paid': 'Отметка оплаты',
  'payment.unpaid': 'Отмена оплаты',
  'payment.date_changed': 'Исправление даты оплаты',
  'payment.amount_changed': 'Изменение суммы периода',
  'payment.terms_changed': 'Изменение условий платежа',
  'user.created': 'Создание пользователя',
  'user.updated': 'Изменение пользователя',
  'user.deleted': 'Удаление пользователя',
  'password.changed': 'Смена своего пароля',
  'payment.receipt_updated': 'Изменение подтверждения оплаты',
  'payment.receipt_deleted': 'Удаление подтверждения оплаты',
}
const actions = Object.keys(auditActionLabels)
const maxOffset = 1_000_000

export function defaultActivityFilters(): AuditFilters {
  return { date_from: '', date_to: '', actor: '', action: '', query: '', limit: 12, offset: 0 }
}

/** Calendar boundaries are strings; they never pass through the browser's timezone. */
function calendarDate(value: string | null): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return ''
  const [year, month, day] = value.split('-').map(Number)
  if (year < 1 || month < 1 || month > 12 || day < 1) return ''
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  return day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ? value : ''
}
function text(value: string | null, max: number): string {
  return Array.from(value || '').filter(character => {
    const code = character.codePointAt(0) ?? 0
    return code > 31 && (code < 127 || code > 159)
  }).slice(0, max).join('').trim()
}
function integer(value: string | null): number {
  return value && /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : 0
}

export function readActivityRoute(hash: string): AuditFilters {
  const defaults = defaultActivityFilters()
  const params = new URLSearchParams(hash.replace(/^#activity(?:\?|$)/, ''))
  const from = calendarDate(params.get('date_from'))
  const to = calendarDate(params.get('date_to'))
  const reversed = Boolean(from && to && from > to)
  const invalid = (params.has('date_from') && params.get('date_from') !== '' && !from) || (params.has('date_to') && params.get('date_to') !== '' && !to)
  const action = params.get('action') || ''
  const limit = integer(params.get('limit'))
  return {
    date_from: reversed || invalid ? '' : from,
    date_to: reversed || invalid ? '' : to,
    actor: text(params.get('actor'), 64),
    action: actions.includes(action) ? action as AuditAction : '',
    query: text(params.get('q'), 200),
    limit: [12, 24].includes(limit) ? limit : defaults.limit,
    offset: Math.min(integer(params.get('offset')), maxOffset),
  }
}

export function activityHash(filters: AuditFilters): string {
  const params = new URLSearchParams()
  const from = calendarDate(filters.date_from)
  const to = calendarDate(filters.date_to)
  if (!from || !to || from <= to) {
    if (from) params.set('date_from', from)
    if (to) params.set('date_to', to)
  }
  const actor = text(filters.actor, 64), query = text(filters.query, 200)
  if (actor) params.set('actor', actor)
  if (actions.includes(filters.action)) params.set('action', filters.action)
  if (query) params.set('q', query)
  params.set('limit', [12, 24].includes(filters.limit) ? String(filters.limit) : '12')
  params.set('offset', String(Number.isSafeInteger(filters.offset) && filters.offset >= 0 ? Math.min(filters.offset, maxOffset) : 0))
  return '#activity?' + params.toString()
}

/** Technical timestamps are instants. Use the same business timezone as the server filters. */
export function activityDay(timestamp: string, timezone: string): string {
  const parsed = new Date(timestamp)
  if (Number.isNaN(parsed.valueOf())) return ''
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(parsed)
  const part = (type: string) => parts.find(value => value.type === type)?.value || ''
  return `${part('year').padStart(4, '0')}-${part('month')}-${part('day')}`
}
