import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, Clock3, History, Info, RefreshCw, Send } from 'lucide-react'
import { api, ApiError } from '../api/client'
import type { Currency, OccurrenceFilters, Page, PaymentOccurrence, PaymentSummary } from '../types/api'
import { dateLabel, money, monthLabel, monthRange } from '../lib/format'
import { Drawer, EmptyState, ErrorNotice, LoadingRows, Pagination } from './UI'
import { PaymentStatus } from './PaymentStatus'
import { DatePicker } from './DatePicker'
import { SelectField } from './SelectField'

type RuleSelection = { id: string; title: string } | null
type Props = { mode: 'payments' | 'history'; revision: number; today: string; selectedRule: RuleSelection; onClearRule: () => void; onHistory: (id: string, title: string) => void; onChanged: () => void; notify: (message: string) => void }
type FilterState = { date_from: string; date_to: string; currency: string; tab: string }
const currencies: Currency[] = ['RUB', 'USD', 'EUR']
const currencyNames = { RUB: 'Рубли', USD: 'Доллары', EUR: 'Евро' }

function Summary({ dates, revision }: { dates: { date_from: string; date_to: string }; revision: number }) {
  const [summary, setSummary] = useState<PaymentSummary | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let alive = true
    setSummary(null); setError(null)
    api.getSummary(dates).then(value => { if (alive) setSummary(value) }).catch(reason => { if (alive) setError(reason) })
    return () => { alive = false }
  }, [dates, revision, retry])
  if (error) return <ErrorNotice error={error} onRetry={() => setRetry(value => value + 1)}/>
  if (!summary) return <div className="summary-grid" aria-label="Загрузка сводки" aria-busy="true">{currencies.map(currency => <div className="currency-card" key={currency}><div className="skeleton" style={{ height: 23, marginBottom: 20 }}/><div className="skeleton" style={{ height: 35, marginBottom: 20 }}/><div className="skeleton" style={{ height: 80 }}/></div>)}</div>
  return <section aria-label="Сводка обязательств по валютам"><p className="summary-caption">По срокам {dateLabel(summary.date_from)}–{dateLabel(summary.date_to)} · состояние на {dateLabel(summary.as_of_date)}, МСК · все статусы и валюты</p><div className="summary-grid">{currencies.map(currency => {
    const total = summary.totals[currency]
    return <article className="currency-card" key={currency}><div className="currency-label"><strong>{currencyNames[currency]}</strong><span className="pill">{currency}</span></div><span className="muted">Всего по срокам</span><strong className="currency-amount">{money(total.planned, currency)}</strong><dl className="currency-breakdown"><div><dt>Оплачено</dt><dd>{money(total.paid, currency)}</dd></div><div><dt>Не оплачено</dt><dd>{money(total.unpaid, currency)}</dd></div><div className="overdue"><dt>Из них просрочено</dt><dd>{money(total.overdue, currency)}</dd></div></dl></article>
  })}</div></section>
}

function PaymentDrawer({ initial, today, onClose, onSaved, onHistory }: { initial: PaymentOccurrence; today: string; onClose: () => void; onSaved: (item: PaymentOccurrence) => void; onHistory: () => void }) {
  const [item, setItem] = useState(initial)
  const [paidOn, setPaidOn] = useState(initial.paid_on || today)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [fieldError, setFieldError] = useState('')
  const guard = useRef(false)
  useEffect(() => {
    let alive = true
    api.getOccurrence(initial.id).then(value => { if (alive) { setItem(value); setPaidOn(value.paid_on || today) } }).catch(reason => { if (alive) setError(reason) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [initial.id, today])
  async function save(paid: boolean) {
    if (guard.current) return
    const actualPaidOn = paidOn
    setPaidOn(actualPaidOn)
    if (paid && (!actualPaidOn || actualPaidOn > today)) { setFieldError('Укажите фактическую дату не позже сегодняшнего дня по МСК.'); return }
    guard.current = true; setBusy(true); setError(null); setFieldError('')
    try {
      const updated = await api.updateOccurrence(item.id, paid ? { status: 'paid', paid_on: actualPaidOn } : { status: 'unpaid', paid_on: null })
      onSaved(updated)
    } catch (reason) {
      setError(reason)
      if (reason instanceof ApiError) setFieldError(reason.details.find(detail => detail.field === 'paid_on')?.message || '')
    } finally { guard.current = false; setBusy(false) }
  }
  return <Drawer canClose={!busy} title={item.status === 'paid' ? 'Изменить оплату' : 'Отметить оплату'} subtitle="Изменение относится только к этому периоду." onClose={() => { if (!guard.current) onClose() }}><div className="payment-detail"><h3 className="payment-title">{item.title}</h3><dl><div><dt>Сумма</dt><dd>{money(item.amount, item.currency)}</dd></div><div><dt>Срок оплаты</dt><dd>{dateLabel(item.due_date)}</dd></div><div><dt>Статус</dt><dd><PaymentStatus item={item}/></dd></div>{item.days_late > 0 && <div><dt>Дней опоздания</dt><dd>{item.days_late}</dd></div>}</dl>{!item.recurring_payment_is_active && <div className="notice"><Info size={18}/><p>Регулярный платёж прекращён. Этот период сохранён в истории, его оплату можно исправить.</p></div>}</div>{error ? <ErrorNotice error={error}/> : null}<form noValidate onSubmit={(event: FormEvent) => { event.preventDefault(); void save(true) }}><div className="field"><label htmlFor="paid-on">Фактическая дата оплаты</label><DatePicker name="paid_on" id="paid-on" today={today} aria-label="Фактическая дата оплаты" required max={today} value={paidOn} onChange={setPaidOn} disabled={busy || loading} aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? "paid-on-hint paid-on-error" : "paid-on-hint"}/><small id="paid-on-hint">Досрочная оплата разрешена. Сегодня по МСК: {dateLabel(today)}.</small>{fieldError && <span id="paid-on-error" className="field-error" role="alert">{fieldError}</span>}</div><div className="notice"><Info size={18}/><p>Вы подтверждаете уже выполненную оплату. Дата срока остаётся прежней; просрочку пересчитает сервер.</p></div><div className="form-actions"><button className="btn btn-primary" type="submit" disabled={busy || loading}>{busy ? <span className="spinner"/> : <Check size={17}/>} {item.status === 'paid' ? 'Сохранить дату' : 'Подтвердить оплату'}</button>{item.status === 'paid' && <button className="btn btn-danger" type="button" disabled={busy || loading} onClick={() => void save(false)}>Отменить отметку оплаты</button>}</div></form><button type="button" className="btn btn-secondary" style={{ marginTop: 24 }} disabled={busy} onClick={onHistory}><History size={16}/> Вся история платежа</button></Drawer>
}

export function PaymentsView({ mode, revision, today, selectedRule, onClearRule, onHistory, onChanged, notify }: Props) {
  const history = mode === 'history'
  const [filters, setFilters] = useState<FilterState>(() => ({ ...(history ? { date_from: '', date_to: '' } : monthRange(today.slice(0,7))), currency: '', tab: 'all' }))
  const [draft, setDraft] = useState(filters)
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(6)
  const [page, setPage] = useState<Page<PaymentOccurrence> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [filterError, setFilterError] = useState('')
  const [retry, setRetry] = useState(0)
  const [selected, setSelected] = useState<PaymentOccurrence | null>(null)
  const lastQuery = useRef('')
  const query = useMemo<OccurrenceFilters>(() => ({ date_from: filters.date_from || undefined, date_to: filters.date_to || undefined, currency: filters.currency as Currency || undefined, status: filters.tab === 'paid' ? 'paid' : ['unpaid','overdue'].includes(filters.tab) ? 'unpaid' : undefined, is_overdue: filters.tab === 'overdue' ? true : undefined, recurring_payment_id: selectedRule?.id, limit, offset }), [filters, selectedRule?.id, limit, offset])
  const summaryDates = useMemo(() => ({ date_from: filters.date_from, date_to: filters.date_to }), [filters.date_from, filters.date_to])
  useEffect(() => {
    let alive = true
    const key = JSON.stringify(query)
    if (lastQuery.current !== key) setPage(null)
    lastQuery.current = key
    setLoading(true); setError(null)
    api.listOccurrences(query).then(value => { if (alive) { setPage(value); if (value.total && value.items.length === 0 && offset > 0) setOffset(Math.max(0, offset - limit)) } }).catch(reason => { if (alive) setError(reason) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [query, revision, retry, offset, limit])
  function apply(event: FormEvent) {
    event.preventDefault()
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setFilterError('Начало периода должно быть не позже конца.'); return }
    if (!history && (!draft.date_from || !draft.date_to)) { setFilterError('Для сводки укажите обе границы. Для всей истории откройте раздел «История».'); return }
    if (!history && draft.date_to > monthRange(today.slice(0,7)).date_to) { setFilterError('Сводка доступна до конца текущего месяца. Будущие периоды можно посмотреть в истории.'); return }
    setFilterError(''); setOffset(0); setFilters(draft)
  }
  function tab(value: string) { setOffset(0); setFilters(previous => ({ ...previous, tab: value })); setDraft(previous => ({ ...previous, tab: value })) }
  function saved(item: PaymentOccurrence) {
    setPage(previous => previous ? { ...previous, items: previous.items.map(row => row.id === item.id ? item : row) } : previous)
    setSelected(null); onChanged(); notify(item.status === 'unpaid' ? 'Отметка оплаты отменена. Дата оплаты очищена.' : item.paid_late ? 'Оплата сохранена. Период оплачен с опозданием.' : 'Оплата сохранена. Срок не изменился.')
  }
  return <>
    {!history && <Summary dates={summaryDates} revision={revision}/>}
    <section className="panel" aria-label={history ? 'История периодов' : 'Периоды оплаты'} aria-busy={loading}>
      <div className="section-head"><div><h2>{history ? 'Все периоды' : 'Периоды оплаты'}{page && <span className="pill">{page.total}</span>}</h2><p>{history ? 'Сохраняем прошлые оплаты и периоды прекращённых платежей.' : 'Сначала ближайшие сроки. Статусы и итоговые суммы рассчитывает сервер.'}</p></div><button className="icon-button" type="button" aria-label="Обновить список и сводку" disabled={loading} onClick={() => { setRetry(value => value + 1); onChanged() }}><RefreshCw size={17}/></button></div>
      {selectedRule && <div className="history-chip"><History size={16}/><strong>{selectedRule.title}</strong><button type="button" className="btn btn-secondary btn-small" onClick={() => { setOffset(0); onClearRule() }}>Все платежи</button></div>}
      <div className="status-tabs" role="group" aria-label="Фильтр статуса">{[['all','Все'],['unpaid','К оплате'],['overdue','Просрочено'],['paid','Оплачено']].map(([value,label]) => <button className={`status-tab ${filters.tab === value ? 'active' : ''}`} type="button" aria-pressed={filters.tab === value} key={value} onClick={() => tab(value)}>{label}</button>)}</div>
      <form className="toolbar" onSubmit={apply}>
        <div className="field"><label htmlFor="date-from">Срок оплаты с</label><DatePicker id="date-from" today={today} aria-label="Срок оплаты с" value={draft.date_from} onChange={date => setDraft(value => ({ ...value, date_from: date }))} required={!history}/></div>
        <div className="field"><label htmlFor="date-to">Срок оплаты по</label><DatePicker id="date-to" today={today} aria-label="Срок оплаты по" value={draft.date_to} onChange={date => setDraft(value => ({ ...value, date_to: date }))} required={!history}/></div>
        <div className="field"><label htmlFor="currency-filter">Валюта</label><SelectField id="currency-filter" value={draft.currency} onChange={currency => setDraft(value => ({ ...value, currency }))} options={[{ value: "", label: "Все валюты", description: "RUB, USD и EUR" }, ...currencies.map(currency => ({ value: currency, label: currency, description: currencyNames[currency] }))]}/></div>
        <button className="btn btn-secondary" type="submit">Применить</button>
        <button className="btn btn-secondary" type="button" onClick={() => { const value = { ...(history ? { date_from:'', date_to:'' } : monthRange(today.slice(0,7))), currency:'', tab:'all' }; setDraft(value); setFilters(value); setOffset(0); setFilterError(''); onClearRule() }}>Сбросить</button>
      </form>
      {filterError && <p className="query-error" role="alert">{filterError}</p>}
      {error ? <ErrorNotice error={error} onRetry={() => setRetry(value => value + 1)}/> : null}
      {loading && !page ? <LoadingRows/> : !error && page?.items.length === 0 ? <EmptyState title="Платежей не найдено">Попробуйте изменить даты или сбросить фильтры. Прекращённые платежи остаются в истории.</EmptyState> : page && <div className="table-wrap"><table className="data-table"><caption className="sr-only">{history ? 'История платежных периодов' : 'Платежи за выбранный период'}</caption><thead><tr><th scope="col">Платёж</th><th scope="col">Сумма</th><th scope="col">Срок</th><th scope="col">Статус</th><th scope="col">Дата оплаты</th><th scope="col">Действия</th></tr></thead><tbody>{page.items.map(item => {
        return <tr key={item.id}><td data-label="Платёж"><button className="payment-title" type="button" onClick={() => setSelected(item)}>{item.title}</button><span className="payment-period">{monthLabel(item.due_date.slice(0,7))}{!item.recurring_payment_is_active && ' · прекращён'}</span></td><td data-label="Сумма" className={item.amount.split('.')[0].length > 9 ? 'money-large' : ''}><span className="money">{money(item.amount, item.currency)}</span></td><td data-label="Срок" className="date-cell">{dateLabel(item.due_date)}</td><td data-label="Статус"><PaymentStatus item={item}/>{item.days_late > 0 && <span className="payment-period">Опоздание: {item.days_late} дн.</span>}</td><td data-label="Дата оплаты" className="date-cell">{dateLabel(item.paid_on)}</td><td data-label="Действия"><div className="inline-actions"><button className={`btn btn-small ${item.status === 'unpaid' ? 'btn-primary' : 'btn-secondary'}`} type="button" onClick={() => setSelected(item)}>{item.status === 'unpaid' ? 'Отметить оплату' : 'Изменить'}</button><button className="icon-button" type="button" aria-label={`История: ${item.title}`} onClick={() => onHistory(item.recurring_payment_id, item.title)}><History size={16}/></button></div></td></tr>
      })}</tbody></table></div>}
      {page && !error && <><div className="page-size"><label htmlFor="page-size">На странице</label><SelectField id="page-size" className="ik-select-compact" value={String(limit)} onChange={size => { setLimit(Number(size)); setOffset(0) }} options={[6, 12, 24].map(size => ({ value: String(size), label: String(size) }))}/></div><Pagination total={page.total} limit={limit} offset={offset} onPage={setOffset}/></>}
    </section>
    <div className="footer-note"><span><Send size={14}/> Напоминание в Telegram — за 3 дня до срока</span><span><Clock3 size={14}/> Календарные даты по МСК</span></div>
    {history && <p className="summary-caption"><Info size={14}/> Прекращение повторения не отменяет уже возникшие обязательства и не удаляет историю.</p>}
    {selected && <PaymentDrawer key={selected.id} initial={selected} today={today} onClose={() => setSelected(null)} onSaved={saved} onHistory={() => { setSelected(null); onHistory(selected.recurring_payment_id, selected.title) }}/>}
  </>
}

