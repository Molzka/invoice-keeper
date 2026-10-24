import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, ArrowUpRight, CalendarClock, Check, CirclePlus, KeyRound, ListChecks, RefreshCw, Search, ShieldCheck, SquarePen, Undo2, UserMinus, UserPlus, UserRound, X } from './BrandIcons'
import { API_MODE, ApiError } from '../api/client'
import { activitySource } from '../api/activity'
import type { AuditAction, AuditEvent, AuditFilters } from '../types/activity'
import type { Page } from '../types/api'
import { activityDay, activityHash, auditActionLabels, defaultActivityFilters, readActivityRoute } from '../lib/activity-route'
import { writeWorkspaceHash } from '../lib/useWorkspaceRoute'
import { dateLabel, money } from '../lib/format'
import { DatePicker } from './DatePicker'
import { SelectField } from './SelectField'
import { Drawer, EmptyState, ErrorNotice, Pagination } from './UI'
import { PageHeader } from './PageHeader'

type Props = { isAdmin: boolean; revision: number; today: string; timezone: string; onHistory: (id: string, title: string) => void }
const actionVisuals = {
  'payment.deleted': { icon: X, tone: 'muted' },
  'payment.period_deleted': { icon: X, tone: 'muted' },
  'payment.amount_changed': { icon: SquarePen, tone: 'cyan' },
  'payment.terms_changed': { icon: CalendarClock, tone: 'violet' },
  'payment.created': { icon: CirclePlus, tone: 'cyan' },
  'payment.stopped': { icon: X, tone: 'muted' },
  'payment.paid': { icon: Check, tone: 'green' },
  'payment.unpaid': { icon: Undo2, tone: 'amber' },
  'payment.date_changed': { icon: CalendarClock, tone: 'cyan' },
  'payment.receipt_updated': { icon: SquarePen, tone: 'cyan' },
  'payment.receipt_deleted': { icon: X, tone: 'muted' },
  'user.created': { icon: UserPlus, tone: 'violet' },
  'user.updated': { icon: SquarePen, tone: 'violet' },
  'user.deleted': { icon: UserMinus, tone: 'muted' },
  'password.changed': { icon: KeyRound, tone: 'violet' },
} as const
const dayFormat = new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
function changeValue(field: string, value: string | null) {
  if (value === null || value === '') return 'Не указано'
  if (['due_date', 'first_due_date', 'paid_on', 'amount_effective_from'].includes(field) && /^\d{4}-\d{2}-\d{2}$/.test(value)) return dateLabel(value)
  const amount = field === 'amount' ? value.match(/^(\d+\.\d{2}) (RUB|USD|EUR)$/) : null
  return amount ? money(amount[1], amount[2] as 'RUB' | 'USD' | 'EUR') : value
}
function timestampTime(value: string, timezone: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.valueOf()) ? 'Время не указано' : new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', timeZone: timezone }).format(parsed)
}
function dayTitle(day: string, today: string) {
  if (!day) return 'Дата не указана'
  if (day === today) return 'Сегодня · ' + dateLabel(day)
  return dayFormat.format(new Date(day + 'T12:00:00Z')).replace(' г.', '')
}
function subscribe(onChange: () => void) {
  for (const event of ['hashchange', 'popstate', 'invoice:routechange']) window.addEventListener(event, onChange)
  return () => { for (const event of ['hashchange', 'popstate', 'invoice:routechange']) window.removeEventListener(event, onChange) }
}
function snapshot() { return window.location.hash }

function ActivityFilters({ filters, today, onApply, onReset }: { filters: AuditFilters; today: string; onApply: (filters: AuditFilters) => void; onReset: () => void }) {
  const [draft, setDraft] = useState(filters)
  const [error, setError] = useState('')
  function apply(event: FormEvent) {
    event.preventDefault()
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setError('Начало периода должно быть не позже конца.'); return }
    setError('')
    onApply({ ...draft, actor: draft.actor.trim(), query: draft.query.trim(), offset: 0 })
  }
  function reset() {
    setDraft(defaultActivityFilters())
    setError('')
    onReset()
  }
  return <><form className="activity-filters" onSubmit={apply} aria-label="Фильтры журнала действий">
    <div className="field activity-search"><label htmlFor="activity-search">Поиск по событиям</label><div className="activity-search-input"><Search size={17} aria-hidden="true"/><input id="activity-search" type="search" value={draft.query} onChange={event => setDraft(value => ({ ...value, query: event.target.value }))} placeholder="Название платежа или пользователь" maxLength={200}/></div></div>
    <div className="field"><label htmlFor="activity-actor">Пользователь</label><input id="activity-actor" value={draft.actor} onChange={event => setDraft(value => ({ ...value, actor: event.target.value }))} placeholder="Все пользователи" autoComplete="off" maxLength={64}/></div>
    <div className="field"><label htmlFor="activity-action">Действие</label><SelectField id="activity-action" value={draft.action} onChange={action => setDraft(value => ({ ...value, action: action as AuditAction | '' }))} options={[{ value: '', label: 'Все действия' }, ...Object.entries(auditActionLabels).map(([value, label]) => ({ value, label }))]}/></div>
    <div className="field"><label htmlFor="activity-from">Дата события с</label><DatePicker id="activity-from" value={draft.date_from} today={today} onChange={date_from => setDraft(value => ({ ...value, date_from }))} aria-label="Дата события с" aria-invalid={Boolean(error)} aria-describedby={error ? 'activity-filter-error' : undefined}/></div>
    <div className="field"><label htmlFor="activity-to">Дата события по</label><DatePicker id="activity-to" value={draft.date_to} today={today} onChange={date_to => setDraft(value => ({ ...value, date_to }))} aria-label="Дата события по" aria-invalid={Boolean(error)} aria-describedby={error ? 'activity-filter-error' : undefined}/></div>
    <div className="activity-filter-actions"><button type="submit" className="btn btn-primary">Применить</button><button type="button" className="btn btn-danger" onClick={reset}>Сбросить</button></div>
  </form>{error && <p id="activity-filter-error" className="query-error activity-filter-error" role="alert">{error}</p>}</>
}

function ActivityDetails({ event, onClose, onHistory, timezone }: { event: AuditEvent; onClose: () => void; onHistory: Props['onHistory']; timezone: string }) {
  const visual = actionVisuals[event.action]
  const Icon = visual.icon
  // A second display boundary prevents credentials accidentally added by a future adapter from rendering.
  const changes = event.changes.filter(change => !/password|пароль|token|токен|secret|cookie|session|csrf/i.test(change.field + ' ' + change.label))
  return <Drawer title="Подробности события" subtitle="События доступны только для просмотра." onClose={onClose}>
    <div className="activity-detail-title"><span className="activity-event-icon" data-tone={visual.tone}><Icon size={21} aria-hidden="true"/></span><div><p>{auditActionLabels[event.action]}</p><h3>{event.entity.title}</h3></div></div>
    <dl className="activity-detail-meta"><div><dt>Пользователь</dt><dd><UserRound size={15} aria-hidden="true"/>{event.actor.username}</dd></div><div><dt>Когда</dt><dd>{dateLabel(activityDay(event.occurred_at, timezone))}, {timestampTime(event.occurred_at, timezone)} {timezone}</dd></div><div><dt>Объект</dt><dd>{event.entity.type === 'payment' ? 'Регулярный платёж' : event.entity.type === 'user' ? 'Пользователь' : 'Учётная запись'}</dd></div></dl>
    {changes.length > 0 ? <section className="activity-diff" aria-label="Изменённые поля"><h4>Что изменилось</h4><div className="activity-diff-columns" aria-hidden="true"><span>До</span><ArrowRight size={14}/><span>После</span></div>{changes.map((change, index) => <div className="activity-change" key={change.field + ':' + index}><strong>{change.label}</strong><div><span className="activity-before"><span className="sr-only">До: </span>{changeValue(change.field, change.before)}</span><ArrowRight size={15} aria-hidden="true"/><span className="activity-after"><span className="sr-only">После: </span>{changeValue(change.field, change.after)}</span></div></div>)}</section> : <div className="activity-private-note"><ShieldCheck size={19} aria-hidden="true"/><p>{event.action === 'password.changed' ? 'В журнале сохраняется только факт смены пароля. Значения паролей и данные сессии не отображаются.' : 'Для этого события дополнительные изменения полей не переданы.'}</p></div>}
    {event.action === 'payment.stopped' && <p className="activity-retention-note">Прекращение останавливает будущие периоды. История уже созданных платежей сохраняется.</p>}
    <div className="activity-detail-actions">{event.entity.type === 'payment' && <button type="button" className="btn btn-primary" onClick={() => onHistory(event.entity.id, event.entity.title)}>История платежа<ArrowUpRight size={16} aria-hidden="true"/></button>}<button type="button" className="btn btn-secondary" data-drawer-close="">Закрыть</button></div>
  </Drawer>
}

export function ActivityView({ isAdmin, revision, today, timezone, onHistory }: Props) {
  const hash = useSyncExternalStore(subscribe, snapshot)
  const filters = useMemo(() => readActivityRoute(hash), [hash])
  const [page, setPage] = useState<Page<AuditEvent> | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  const [selected, setSelected] = useState<AuditEvent | null>(null)
  useEffect(() => {
    if (!isAdmin) return
    let alive = true
    setPage(null); setError(null)
    activitySource.list(filters).then(value => {
      if (!alive) return
      if (filters.offset > 0 && filters.offset >= value.total) {
        const offset = value.total ? Math.floor((value.total - 1) / filters.limit) * filters.limit : 0
        writeWorkspaceHash(activityHash({ ...filters, offset }), true)
        return
      }
      setPage(value)
    }).catch(reason => { if (alive) setError(reason) })
    return () => { alive = false }
  }, [filters, isAdmin, revision, retry, timezone])
  if (!isAdmin) return <ErrorNotice error={new ApiError(403, 'FORBIDDEN', 'Журнал действий доступен администратору.')}/>
  const groups = new Map<string, AuditEvent[]>()
  page?.items.forEach(event => { const day = activityDay(event.occurred_at, timezone); groups.set(day, [...(groups.get(day) || []), event]) })
  const hasFilters = Boolean(filters.date_from || filters.date_to || filters.actor || filters.action || filters.query)
  return <>
    <PageHeader kind="activity" title="Журнал действий" eyebrow={<>Прозрачная работа команды{API_MODE === 'mock' && <span className="demo-badge">Демо</span>}</>} description="Кто изменил платёж, отметил оплату или обновил доступ — вся последовательность событий."/>
    {API_MODE === 'mock' && <div className="activity-demo-note"><ListChecks size={17} aria-hidden="true"/><p>Демонстрационные события. Новые действия в демо появляются здесь до обновления страницы.</p><span>{timezone}</span></div>}
    <section className="panel activity-panel" aria-labelledby="activity-events-title">
      <div className="section-head"><div><h2 id="activity-events-title">События команды{page && <span className="pill">{page.total}</span>}</h2><p>От новых к старым. Время событий — {timezone}.</p></div><button type="button" className="icon-button" disabled={!page && !error} aria-label="Обновить журнал действий" onClick={() => setRetry(value => value + 1)}><RefreshCw size={17}/></button></div>
      <ActivityFilters key={JSON.stringify(filters)} filters={filters} today={today} onApply={value => writeWorkspaceHash(activityHash(value))} onReset={() => writeWorkspaceHash(activityHash(defaultActivityFilters()))}/>
      {error ? <div className="activity-load-error"><ErrorNotice error={error} onRetry={() => setRetry(value => value + 1)}/></div> : !page ? <div className="activity-loading" role="status" aria-label="Загрузка журнала действий">{[1,2,3].map(value => <div className="skeleton" key={value}/>)}</div> : page.items.length === 0 ? <EmptyState title={hasFilters ? 'По этим фильтрам событий нет' : 'Событий пока нет'}>{hasFilters ? 'Измените условия поиска или сбросьте фильтры.' : 'Новые действия команды появятся здесь после изменений.'}</EmptyState> : <div className="activity-timeline">{Array.from(groups, ([day, events]) => <section className="activity-day" aria-label={dayTitle(day, today)} key={day}><h3><span>{dayTitle(day, today)}</span><span className="activity-day-count">{events.length}</span></h3><ol>{events.map(event => { const visual = actionVisuals[event.action]; const Icon = visual.icon; return <li className="activity-event" key={event.id}><span className="activity-event-icon" data-tone={visual.tone}><Icon size={18} aria-hidden="true"/></span><div className="activity-event-body"><div className="activity-event-top"><span className="activity-action-label" data-tone={visual.tone}>{auditActionLabels[event.action]}</span><time dateTime={event.occurred_at}>{timestampTime(event.occurred_at, timezone)}</time></div><h4>{event.entity.title}</h4><div className="activity-event-bottom"><span className="activity-actor"><UserRound size={13} aria-hidden="true"/>{event.actor.username}</span><button type="button" className="activity-details-link" onClick={() => setSelected(event)} aria-label={`Подробнее: ${auditActionLabels[event.action]}, ${event.entity.title}`}>Подробнее<ArrowUpRight size={14} aria-hidden="true"/></button></div></div></li> })}</ol></section>)}</div>}
      {page && page.total > 0 && <div className="activity-pagination"><div className="activity-page-size"><label htmlFor="activity-page-size">На странице</label><SelectField id="activity-page-size" className="ik-select-compact" value={String(filters.limit)} onChange={limit => writeWorkspaceHash(activityHash({ ...filters, limit: Number(limit), offset: 0 }))} options={[{ value: '12', label: '12' }, { value: '24', label: '24' }]}/></div><Pagination total={page.total} limit={filters.limit} offset={filters.offset} onPage={offset => writeWorkspaceHash(activityHash({ ...filters, offset }))}/></div>}
    </section>
    {selected && <ActivityDetails timezone={timezone} event={selected} onClose={() => setSelected(null)} onHistory={(id, title) => { setSelected(null); onHistory(id, title) }}/>}<p className="activity-footer"><ShieldCheck size={14} aria-hidden="true"/>История действий доступна только для просмотра</p>
  </>
}
