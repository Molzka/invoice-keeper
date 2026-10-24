import type { PaymentOccurrence, RecurringPayment, User } from '../types/api'
import { AUDIT_ACTION_LABELS } from '../types/activity'
import type { AuditChange, AuditEvent, AuditFilters, AuditPage } from '../types/activity'
import { APP_TIMEZONE, businessNowIso, businessToday, DEMO_TODAY, shiftCalendarDays } from '../config/demo'

// This whitelist is intentionally unrelated to arbitrary mutation bodies: secrets never enter the log.
const safeFields = new Set(['title', 'amount', 'currency', 'first_due_date', 'status', 'paid_on', 'due_date', 'is_active', 'username', 'receipt'])
const copy = <T>(value: T): T => structuredClone(value)
export type NewAuditEvent = Pick<AuditEvent, 'actor' | 'action' | 'entity'> & { changes?: AuditChange[]; occurred_at?: string }

export function auditMoscowDate(timestamp: string): string { return businessToday('real', new Date(timestamp), APP_TIMEZONE) }

export function filterAuditEvents(events: AuditEvent[], filters: AuditFilters): AuditPage {
  const actor = filters.actor.trim().toLocaleLowerCase('ru')
  const query = filters.query.trim().toLocaleLowerCase('ru')
  const items = events.filter(event => {
    const day = auditMoscowDate(event.occurred_at)
    return (!filters.date_from || day >= filters.date_from) && (!filters.date_to || day <= filters.date_to)
      && (!actor || event.actor.username.toLocaleLowerCase('ru').includes(actor))
      && (!filters.action || event.action === filters.action)
      && (!query || [event.entity.title, event.actor.username, AUDIT_ACTION_LABELS[event.action]].join(' ').toLocaleLowerCase('ru').includes(query))
  }).sort((a, b) => b.occurred_at.localeCompare(a.occurred_at) || b.id.localeCompare(a.id))
  return { items: copy(items.slice(filters.offset, filters.offset + filters.limit)), total: items.length, limit: filters.limit, offset: filters.offset }
}

export function createAuditStore(seed: AuditEvent[] = []) {
  const events = copy(seed)
  let sequence = seed.length
  return {
    append(input: NewAuditEvent) {
      const changes = (input.changes || []).filter(change => safeFields.has(change.field) && change.before !== change.after)
        .map(({ field, label, before, after }) => ({ field, label, before, after }))
      const event: AuditEvent = { id: `demo-event-${String(++sequence).padStart(8, '0')}`, occurred_at: input.occurred_at || businessNowIso('mock'),
        actor: { id: input.actor.id, username: input.actor.username }, action: input.action,
        entity: { type: input.entity.type, id: input.entity.id, title: input.entity.title }, changes }
      events.push(event)
      return copy(event)
    },
    list: (filters: AuditFilters) => filterAuditEvents(events, filters),
  }
}

/** Illustrative records derived from the same demo users, rules and periods. Reload resets them. */
export function createAuditFixtures(users: User[], rules: RecurringPayment[], occurrences: PaymentOccurrence[]): AuditEvent[] {
  const store = createAuditStore()
  const actor = users.find(user => user.role === 'admin')!
  const participant = users.find(user => user.username === 'ivan') || actor
  for (const rule of rules) store.append({ actor, action: 'payment.created', occurred_at: rule.created_at,
    entity: { type: 'payment', id: rule.id, title: rule.title }, changes: [
      { field: 'amount', label: 'Сумма', before: null, after: `${rule.amount} ${rule.currency}` },
      { field: 'first_due_date', label: 'Первый срок', before: null, after: rule.first_due_date },
    ] })
  for (const period of occurrences.filter(item => item.status === 'paid').slice(-19)) store.append({ actor: participant, action: 'payment.paid',
    occurred_at: `${period.paid_on}T08:15:00Z`, entity: { type: 'payment', id: period.recurring_payment_id, title: period.title },
    changes: [{ field: 'due_date', label: 'Период со сроком', before: null, after: period.due_date },
      { field: 'status', label: 'Статус', before: 'Не оплачено', after: 'Оплачено' },
      { field: 'paid_on', label: 'Дата оплаты', before: null, after: period.paid_on }] })
  for (const user of users.filter(item => item.role === 'user')) store.append({ actor, action: 'user.created', occurred_at: user.created_at,
    entity: { type: 'user', id: user.id, title: user.username }, changes: [{ field: 'username', label: 'Логин', before: null, after: user.username }] })
  const stopped = rules.find(item => !item.is_active)
  if (stopped) store.append({ actor, action: 'payment.stopped', occurred_at: `${DEMO_TODAY.slice(0, 7)}-06T09:00:00Z`,
    entity: { type: 'payment', id: stopped.id, title: stopped.title }, changes: [{ field: 'is_active', label: 'Регулярный платёж', before: 'Действует', after: 'Прекращён' }] })
  store.append({ actor: participant, action: 'password.changed', occurred_at: `${shiftCalendarDays(DEMO_TODAY, -1)}T13:20:00Z`, entity: { type: 'account', id: participant.id, title: participant.username } })
  return store.list({ date_from: '', date_to: '', actor: '', action: '', query: '', limit: 100, offset: 0 }).items
}
