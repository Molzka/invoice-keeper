import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { ArrowUpRight, CalendarDays, ChevronLeft, ChevronRight, RefreshCw } from './BrandIcons'
import { api, API_MODE } from '../api/client'
import type { Currency, PaymentOccurrence } from '../types/api'
import { dateLabel, money, monthLabel, statusInfo } from '../lib/format'
import { calendarCells, calendarHash, calendarMonthDays, calendarOccurrenceFilters, calendarTotals, loadCalendarOccurrences, moveCalendarMonth, readCalendarRoute } from '../lib/payment-calendar'
import type { CalendarRoute } from '../lib/payment-calendar'
import { PageHeader } from './PageHeader'
import { DeletePaymentDrawer } from './DeletePaymentDrawer'
import { PaymentEditDrawer } from './PaymentEditDrawer'
import { PaymentDrawer } from './PaymentsView'
import { PaymentStatus } from './PaymentStatus'
import { SelectField } from './SelectField'
import { EmptyState, ErrorNotice } from './UI'

interface Props { isAdmin: boolean; today: string; timezone: string; revision: number; onChanged: () => void; notify: (message: string) => void; onHistory: (id: string, title: string) => void }
const weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const subscribeHash = (changed: () => void) => { window.addEventListener('hashchange', changed); return () => window.removeEventListener('hashchange', changed) }
const hashSnapshot = () => window.location.hash
const statusOptions = [{ value: 'all', label: 'Все статусы' }, { value: 'unpaid', label: 'К оплате' }, { value: 'overdue', label: 'Просрочено' }, { value: 'paid', label: 'Оплачено' }]
const currencyOptions = [{ value: '', label: 'Все валюты' }, { value: 'RUB', label: 'RUB', description: 'Рубли' }, { value: 'USD', label: 'USD', description: 'Доллары' }, { value: 'EUR', label: 'EUR', description: 'Евро' }]

function CalendarPayment({ item, compact = false, open }: { item: PaymentOccurrence; compact?: boolean; open: (item: PaymentOccurrence) => void }) {
  const status = statusInfo(item)
  return <button type="button" className={`calendar-payment ${compact ? 'calendar-payment-compact' : ''}`} data-status={status.className} onClick={() => open(item)} aria-label={`${item.title}, ${money(item.amount, item.currency)}, срок ${dateLabel(item.due_date)}, ${status.text}`}>
    <span className="calendar-payment-title">{item.title}</span><strong>{money(item.amount, item.currency)}</strong>
    {!compact && <><PaymentStatus item={item}/>{item.periodicity !== 'once' && !item.recurring_payment_is_active && <small>Регулярный платёж прекращён</small>}<ArrowUpRight size={16} className="calendar-payment-arrow" aria-hidden="true"/></>}
  </button>
}

function focusDayDetails() {
  const heading = document.getElementById('calendar-day-heading')
  heading?.focus({ preventScroll: true })
  document.getElementById('calendar-day-details')?.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
}

function DayTotals({ items, day }: { items: PaymentOccurrence[]; day: string }) {
  const totals = calendarTotals(items)
  return <section className="calendar-day-totals" aria-label={`Итоги за ${dateLabel(day)}`}>
    <p>Итого за день <span>· по выбранным фильтрам</span></p>
    <dl>{(['RUB', 'USD', 'EUR'] as Currency[]).map(currency => <div key={currency}>
      <dt>{currency}</dt><dd><strong>{money(totals[currency].planned, currency)}</strong>
        <span>Оплачено: {money(totals[currency].paid, currency)}</span>
        <span>К оплате: {money(totals[currency].unpaid, currency)}</span>
        {totals[currency].overdue !== '0.00' && <span className="overdue">Из них просрочено: {money(totals[currency].overdue, currency)}</span>}
      </dd>
    </div>)}</dl>
  </section>
}

export function PaymentCalendar({ isAdmin, today, timezone, revision, onChanged, notify, onHistory }: Props) {
  const hash = useSyncExternalStore(subscribeHash, hashSnapshot)
  const route = useMemo(() => readCalendarRoute(hash, today), [hash, today])
  const [rows, setRows] = useState<PaymentOccurrence[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  const [selected, setSelected] = useState<PaymentOccurrence | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<PaymentOccurrence | null>(null)
  const [editTarget, setEditTarget] = useState<PaymentOccurrence | null>(null)
  const { month, day, currency, status } = route
  const pendingDetails = useRef('')
  useEffect(() => {
    if (pendingDetails.current !== day) return
    pendingDetails.current = ''
    focusDayDetails()
  }, [day])
  const filterKey = `${month}:${currency}:${status}:${revision}:${retry}:${today}:${timezone}`
  // A key identifies the fully loaded month; old rows never appear under new filters.
  const [loadedKey, setLoadedKey] = useState('')
  useEffect(() => {
    let alive = true
    loadCalendarOccurrences(calendarOccurrenceFilters({ month, day: '', currency, status }), api.listOccurrences, () => alive)
      .then(value => { if (alive) { setRows(value); setError(null); setLoadedKey(filterKey) } })
      .catch(reason => { if (alive) { setRows(null); setError(reason); setLoadedKey(filterKey) } })
    return () => { alive = false }
  }, [month, currency, status, revision, retry, today, timezone, filterKey])
  const ready = loadedKey === filterKey
  const visibleRows = ready ? rows : null
  const days = useMemo(() => {
    const grouped = new Map<string, PaymentOccurrence[]>()
    for (const row of visibleRows || []) grouped.set(row.due_date, [...(grouped.get(row.due_date) || []), row])
    return grouped
  }, [visibleRows])
  const cells = useMemo(() => calendarCells(month), [month])
  const selectedRows = days.get(day) || []
  const previousMonth = moveCalendarMonth(month, -1), nextMonth = moveCalendarMonth(month, 1)
  const future = month > today.slice(0, 7)
  function change(next: Partial<CalendarRoute>) { window.location.hash = calendarHash({ ...route, ...next }).slice(1) }
  function revealDay(date: string) {
    if (date === day) focusDayDetails()
    else { pendingDetails.current = date; change({ day: date }) }
  }
  function changeMonth(next: string | null) {
    if (!next) return
    const number = Math.min(+day.slice(-2), calendarMonthDays(next))
    change({ month: next, day: `${next}-${String(number).padStart(2, '0')}` })
  }
  function saved(item: PaymentOccurrence) { setSelected(null); onChanged(); notify(item.status === 'unpaid' ? 'Отметка оплаты отменена. Календарь обновлён.' : item.paid_late ? 'Оплата сохранена с опозданием. Календарь обновлён.' : 'Оплата сохранена. Календарь обновлён.') }
  return <section className="payment-calendar-page">
    <PageHeader kind="calendar" title="Календарь оплат" description="Сроки на виду. Откройте день или платёж, чтобы посмотреть детали и отметить оплату." eyebrow={<>Рабочее пространство{API_MODE === 'mock' && <span className="demo-badge">Демо</span>}</>}/>
    <section className="payment-calendar-card" aria-label="Календарь сроков платежей">
      <div className="calendar-topline"><div className="calendar-month-control"><span className="calendar-heading-icon" aria-hidden="true"><CalendarDays size={23}/></span><div><p className="eyebrow">План по срокам</p><h2 aria-live="polite">{monthLabel(month)}</h2></div></div><div className="calendar-navigation"><button className="btn btn-secondary btn-small" type="button" onClick={() => change({ month: today.slice(0, 7), day: today })}>Сегодня</button><button className="icon-button" type="button" disabled={!previousMonth} aria-label="Предыдущий месяц" onClick={() => changeMonth(previousMonth)}><ChevronLeft size={18}/></button><button className="icon-button" type="button" disabled={!nextMonth} aria-label="Следующий месяц" onClick={() => changeMonth(nextMonth)}><ChevronRight size={18}/></button><button className="icon-button" type="button" aria-label="Обновить календарь" disabled={!ready} onClick={() => setRetry(value => value + 1)}><RefreshCw size={17}/></button></div></div>
      <div className="calendar-filters"><div className="field"><label htmlFor="calendar-currency">Валюта</label><SelectField id="calendar-currency" value={currency} options={currencyOptions} onChange={value => change({ currency: value as CalendarRoute['currency'] })}/></div><div className="field"><label htmlFor="calendar-status">Статус платежа</label><SelectField id="calendar-status" value={status} options={statusOptions} onChange={value => change({ status: value as CalendarRoute['status'] })}/></div><button className="calendar-clear btn btn-secondary btn-small" type="button" onClick={() => change({ currency: '', status: 'all' })}>Сбросить фильтры</button><p className="calendar-count" role="status">{!ready ? 'Загружаем все периоды…' : error ? 'Данные недоступны' : `Платежей в месяце: ${visibleRows?.length || 0}`}</p></div>
      <p className="calendar-explanation">Платежи расположены по сроку оплаты. Статусы определяет сервер; часовой пояс — {timezone}.{future && ' Будущие периоды ещё могут быть не сформированы.'}</p>
      <div className="calendar-status-legend" aria-label="Обозначения статусов"><span data-status="status-neutral">Не оплачено</span><span data-status="status-danger">Просрочено</span><span data-status="status-success">Оплачено</span><span data-status="status-warning">С опозданием</span></div>
      {!ready ? <div className="calendar-loading" role="status" aria-label="Загрузка календаря" aria-busy="true"><span className="spinner"/><p>Собираем платежи за месяц…</p><div className="calendar-loading-grid" aria-hidden="true">{Array.from({ length: 14 }, (_, index) => <div key={index} className="skeleton"/>)}</div></div> : error ? <div className="calendar-error"><ErrorNotice error={error} onRetry={() => setRetry(value => value + 1)}/></div> : <>
        <div className="calendar-desktop-layout"><div className="calendar-grid-scroll"><table className="calendar-month-table"><caption className="sr-only">Платежи по срокам за {monthLabel(month)}</caption><thead><tr>{weekdays.map(name => <th scope="col" key={name}>{name}</th>)}</tr></thead><tbody>{Array.from({ length: cells.length / 7 }, (_, week) => <tr key={week}>{cells.slice(week * 7, week * 7 + 7).map((date, index) => {
          if (!date) return <td key={`blank-${index}`} className="calendar-blank" aria-hidden="true"/>
          const items = days.get(date) || []
          return <td key={date} data-selected={date === day} data-today={date === today}><button className="calendar-day-number" type="button" aria-label={`${dateLabel(date)}, платежей: ${items.length}${date === today ? ', сегодня' : ''}`} aria-pressed={date === day} onClick={() => change({ day: date })}><span>{+date.slice(-2)}</span>{items.length > 0 && <small>{items.length}</small>}</button><div className="calendar-day-payments">{items.slice(0, 2).map(item => <CalendarPayment key={item.id} compact item={item} open={setSelected}/>)}{items.length > 2 && <button className="calendar-more" type="button" aria-controls="calendar-day-details" onClick={() => revealDay(date)} aria-label={`Все ${items.length} платежей за ${dateLabel(date)}`}>Ещё {items.length - 2} <ArrowUpRight size={12} aria-hidden="true"/></button>}</div></td>
        })}</tr>)}</tbody></table></div>
        <aside id="calendar-day-details" className="calendar-day-panel" aria-label="Платежи выбранного дня"><div className="calendar-day-panel-heading"><span className="calendar-selected-date" aria-hidden="true">{+day.slice(-2)}</span><div><p className="eyebrow">Выбранный день</p><h3 id="calendar-day-heading" tabIndex={-1}>{dateLabel(day)}</h3></div></div><p className="calendar-day-count" aria-live="polite">Платежей: {selectedRows.length}{day === today && ' · Сегодня'}</p>
          {(!future || selectedRows.length > 0) && <DayTotals items={selectedRows} day={day}/>}
          {selectedRows.length ? <div className="calendar-day-detail-list">{selectedRows.map(item => <CalendarPayment key={item.id} item={item} open={setSelected}/>)}</div> : <div className="calendar-day-empty"><CalendarDays size={26} aria-hidden="true"/><h4>На этот день платежей нет</h4><p>{future ? 'Будущие периоды появятся после формирования на сервере.' : currency || status !== 'all' ? 'Попробуйте другие фильтры или выберите день с отметкой.' : 'Выберите другую дату в календаре.'}</p></div>}</aside></div>
        <div className="calendar-mobile-agenda" aria-label="Платежи месяца по дням">{visibleRows?.length ? Array.from(days.entries()).map(([date, items]) => <section className="calendar-agenda-day" key={date}><h3><span>{+date.slice(-2)}</span><span>{dateLabel(date)}{date === today && <small>Сегодня</small>}</span><small>{items.length}</small></h3>
          <DayTotals items={items} day={date}/><div>{items.map(item => <CalendarPayment key={item.id} item={item} open={setSelected}/>)}</div></section>) : <EmptyState title="В этом месяце платежей нет">{future ? 'Будущие периоды ещё могут быть не сформированы на сервере.' : 'Измените месяц или сбросьте фильтры.'}</EmptyState>}</div>
        {!visibleRows?.length && <p className="calendar-month-empty-note" role="status">{future ? 'Сервер пока не вернул периодов на этот месяц. Это не прогноз будущих расходов.' : 'За выбранный месяц и с этими фильтрами платежей не найдено.'}</p>}
      </>}
    </section>
    {deleteTarget && <DeletePaymentDrawer target={{ kind:"period", item:deleteTarget }} onClose={() => { setDeleteTarget(null); onChanged() }} onDeleted={() => { setDeleteTarget(null); onChanged(); notify("Платёж удалён из обязательств.") }}/>}
    {editTarget && <PaymentEditDrawer key={`period:${editTarget.id}`} target={{ ...editTarget, kind: 'period', dueDate: editTarget.due_date }} onSave={async values => { await api.updateOccurrenceDetails(editTarget.id, values) }} onSaved={() => { setEditTarget(null); onChanged(); notify('Изменения платежа сохранены. Календарь обновлён.') }} onClose={refresh => { setEditTarget(null); if (refresh) onChanged() }}/>}
    {selected && <PaymentDrawer key={selected.id} initial={selected} today={today} timezone={timezone} onAttachmentsChanged={onChanged} onDelete={isAdmin ? item => { setSelected(null); setDeleteTarget(item) } : undefined} onEdit={isAdmin ? item => { setSelected(null); setEditTarget(item) } : undefined} onClose={() => setSelected(null)} onSaved={saved} onHistory={() => { const item = selected; setSelected(null); onHistory(item.recurring_payment_id, item.title) }}/>}
  </section>
}
