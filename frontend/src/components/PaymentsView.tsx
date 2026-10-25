import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, MouseEvent } from 'react'
import { ArrowUpRight, ChevronDown, PencilLine, Check, Clock3, History, Info, RefreshCw, Send } from './BrandIcons'
import { api, ApiError } from '../api/client'
import type { Currency, OccurrenceFilters, Page, PaymentOccurrence, PaymentSummary } from '../types/api'
import { dateLabel, money, monthLabel, monthRange } from '../lib/format'
import { recurrenceLabel } from '../lib/recurring-inputs'
import { Drawer, EmptyState, ErrorNotice, LoadingRows, Pagination } from './UI'
import { PaymentStatus } from './PaymentStatus'
import { CurrencyArt } from './CurrencyArt'
import { ReceiptDrawer } from './ReceiptDrawer'
import { DeletePaymentDrawer } from './DeletePaymentDrawer'
import { Paperclip, Trash2 } from './BrandIcons'
import { PaymentEditDrawer } from './PaymentEditDrawer'
import { DatePicker } from './DatePicker'
import { SelectField } from './SelectField'
import { OverdueNotice } from './OverdueNotice'
import { defaultPaymentFilters, paymentHash } from '../lib/payment-route'
import type { PaymentFilters, PaymentPageSize, PaymentRoute, PaymentTab } from '../lib/payment-route'


type RuleSelection = { id: string; title: string } | null
type Props = { isAdmin: boolean; mode: 'payments' | 'history'; route: PaymentRoute; onRouteChange: (next: PaymentRoute, replace?: boolean) => void; revision: number; today: string; timezone: string; selectedRule: RuleSelection; onHistory: (id: string, title: string) => void; onChanged: () => void; notify: (message: string) => void }
const currencies: Currency[] = ['RUB', 'USD', 'EUR']
const currencyNames = { RUB: 'Рубли', USD: 'Доллары', EUR: 'Евро' }


function focusPaymentResults(event: MouseEvent<HTMLAnchorElement>) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
  const heading = document.getElementById('payment-results-heading')
  heading?.focus({ preventScroll: true })
  document.getElementById('payment-results')?.scrollIntoView({ block: 'start', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
}

function Summary({ dates, revision, filters, limit, today, timezone }: { dates: { date_from: string; date_to: string }; revision: number; filters: PaymentFilters; limit: PaymentPageSize; today: string; timezone: string }) {
  const [summary, setSummary] = useState<PaymentSummary | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let alive = true
    setSummary(null); setError(null)
    api.getSummary(dates).then(value => { if (alive) setSummary(value) }).catch(reason => { if (alive) setError(reason) })
    return () => { alive = false }
  }, [dates, revision, retry, today, timezone])
  if (error) return <ErrorNotice error={error} onRetry={() => setRetry(value => value + 1)}/>
  if (!summary) return <section className="payment-summary" aria-label="Загрузка сводки" aria-busy="true"><div className="summary-grid">{currencies.map(currency => <div className="currency-card" key={currency}><div className="skeleton" style={{ height: 23, marginBottom: 20 }}/><div className="skeleton" style={{ height: 35, marginBottom: 20 }}/><div className="skeleton" style={{ height: 80 }}/></div>)}</div><div className="currency-compact-list compact-loading">{currencies.map(currency => <div className="currency-compact-placeholder" key={currency}><span>{currencyNames[currency]}</span><span className="skeleton"/></div>)}</div></section>
  function amountLink(currency: Currency, tab: PaymentTab, amount: string, label: string) {
    // The server's summary dates define the drill-down; unsaved toolbar changes do not.
    const href = paymentHash('payments', { date_from: summary!.date_from, date_to: summary!.date_to, currency, tab }, { limit, offset: 0 })
    return <a className="summary-amount-link" href={href} onClick={focusPaymentResults} aria-label={`${label} в ${currency}: ${money(amount, currency)}`} aria-current={filters.currency === currency && filters.tab === tab ? 'true' : undefined}><span>{money(amount, currency)}</span><ArrowUpRight size={13} aria-hidden="true"/></a>
  }
  function breakdown(currency: Currency) {
    const total = summary!.totals[currency]
    return <dl className="currency-breakdown">
      <div><dt>Оплачено</dt><dd>{amountLink(currency, 'paid', total.paid, 'Оплачено')}</dd></div>
      <div><dt>Не оплачено</dt><dd>{amountLink(currency, 'unpaid', total.unpaid, 'Не оплачено')}</dd></div>
      <div className="overdue"><dt>Из них просрочено</dt><dd>{amountLink(currency, 'overdue', total.overdue, 'Просрочено')}</dd></div>
    </dl>
  }
  return <section className="payment-summary" aria-label="Сводка обязательств по валютам">
    <p className="summary-caption">По срокам {dateLabel(summary.date_from)}–{dateLabel(summary.date_to)} · состояние на {dateLabel(summary.as_of_date)}<span className="summary-context">, {summary.timezone} · все статусы и валюты</span></p>
    <p className="summary-navigation-hint"><ArrowUpRight size={13} aria-hidden="true"/> Нажмите на сумму, чтобы посмотреть соответствующие платежи</p>
    <div className="summary-grid">{currencies.map(currency => {
      const total = summary.totals[currency]
      return <article className="currency-card" data-currency={currency} key={currency}>
        <CurrencyArt currency={currency}/><div className="currency-label"><strong>{currencyNames[currency]}</strong><span className="pill">{currency}</span></div>
        <span className="muted">Всего по срокам</span><strong className="currency-amount" data-large={total.planned.split('.')[0].length > 9}>{amountLink(currency, 'all', total.planned, 'Все платежи')}</strong>
        {breakdown(currency)}
      </article>
    })}</div>
    <div className="currency-compact-list">{currencies.map(currency => <details className="currency-compact" key={currency}>
      <summary data-large={summary.totals[currency].unpaid.split('.')[0].length > 9}><span className="compact-currency-name"><strong>{currencyNames[currency]}</strong><small>{currency}</small></span><span className="compact-currency-amount"><small>К оплате</small><strong>{money(summary.totals[currency].unpaid, currency)}</strong></span><ChevronDown size={16} aria-hidden="true"/></summary>
      <div className="compact-currency-detail"><div className="compact-currency-total"><span>Всего по срокам</span>{amountLink(currency, 'all', summary.totals[currency].planned, 'Все платежи')}</div>{breakdown(currency)}</div>
    </details>)}</div>
  </section>
}

function PaymentFilterToolbar({ filters, history, today, onApply, onReset }: { filters: PaymentFilters; history: boolean; today: string; onApply: (filters: PaymentFilters) => void; onReset: () => void }) {
  const [draft, setDraft] = useState(filters)
  const [filterError, setFilterError] = useState('')
  function apply(event: FormEvent) {
    event.preventDefault()
    if (draft.date_from && draft.date_to && draft.date_from > draft.date_to) { setFilterError('Начало периода должно быть не позже конца.'); return }
    if (!history && (!draft.date_from || !draft.date_to)) { setFilterError('Для сводки укажите обе границы. Для всей истории откройте раздел «История».'); return }
    if (!history && draft.date_to > monthRange(today.slice(0,7)).date_to) { setFilterError('Сводка доступна до конца текущего месяца. Будущие периоды можно посмотреть в истории.'); return }
    setFilterError(''); onApply(draft)
  }
  function reset() {
    // Draft fields can differ even when the applied URL is already at its defaults.
    setDraft(defaultPaymentFilters(history ? 'history' : 'payments', today))
    setFilterError('')
    onReset()
  }
  return <><form className="toolbar" onSubmit={apply}>
    <div className="field"><label htmlFor="date-from">Срок оплаты с</label><DatePicker id="date-from" today={today} aria-label="Срок оплаты с" value={draft.date_from} onChange={date => setDraft(value => ({ ...value, date_from: date }))} required={!history}/></div>
    <div className="field"><label htmlFor="date-to">Срок оплаты по</label><DatePicker id="date-to" today={today} aria-label="Срок оплаты по" value={draft.date_to} onChange={date => setDraft(value => ({ ...value, date_to: date }))} required={!history}/></div>
    <div className="field"><label htmlFor="currency-filter">Валюта</label><SelectField id="currency-filter" value={draft.currency} onChange={currency => setDraft(value => ({ ...value, currency: currency as PaymentFilters['currency'] }))} options={[{ value: "", label: "Все валюты", description: "RUB, USD и EUR" }, ...currencies.map(currency => ({ value: currency, label: currency, description: currencyNames[currency] }))]}/></div>
    <button className="btn btn-secondary" type="submit">Применить</button>
    <button className="btn btn-secondary" type="button" onClick={reset}>Сбросить</button>
  </form>{filterError && <p className="query-error" role="alert">{filterError}</p>}</>
}

export function PaymentDrawer({ initial, initialMode = 'details', today, timezone, onClose, onSaved, onHistory, onEdit, onDelete, onAttachmentsChanged }: { initial: PaymentOccurrence; initialMode?: 'details' | 'payment'; today: string; timezone: string; onClose: () => void; onSaved: (item: PaymentOccurrence) => void; onHistory: () => void; onEdit?: (item: PaymentOccurrence) => void; onDelete?: (item: PaymentOccurrence) => void; onAttachmentsChanged?: () => void }) {
  const [item, setItem] = useState(initial)
  const [mode, setMode] = useState(initialMode)
  const [receiptOpen, setReceiptOpen] = useState(false)
  const [paidOn, setPaidOn] = useState(initial.paid_on || today)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [fieldError, setFieldError] = useState('')
  const guard = useRef(false)
  const openedOn = useRef(today)
  const paidOnEdited = useRef(false)
  function changeMode(next: 'details' | 'payment') {
    setMode(next)
    requestAnimationFrame(() => document.querySelector<HTMLElement>('.drawer-head h2')?.focus())
  }
  useEffect(() => {
    let alive = true
    // Refresh server-derived overdue status at midnight without replacing an edited date.
    api.getOccurrence(initial.id).then(value => {
      if (alive) {
        setItem(value)
        if (!paidOnEdited.current) setPaidOn(value.paid_on || openedOn.current)
      }
    }).catch(reason => { if (alive) setError(reason) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [initial.id, today, timezone])
  async function save(paid: boolean) {
    if (guard.current) return
    const actualPaidOn = paidOn
    setPaidOn(actualPaidOn)
    if (paid && (!actualPaidOn || actualPaidOn > today)) { setFieldError(`Укажите фактическую дату не позже сегодняшнего дня (${timezone}).`); return }
    guard.current = true; setBusy(true); setError(null); setFieldError('')
    try {
      const updated = await api.updateOccurrence(item.id, paid ? { status: 'paid', paid_on: actualPaidOn } : { status: 'unpaid', paid_on: null })
      onSaved(updated)
    } catch (reason) {
      setError(reason)
      if (reason instanceof ApiError) setFieldError(reason.details.find(detail => detail.field === 'paid_on')?.message || '')
    } finally { guard.current = false; setBusy(false) }
  }
  if (receiptOpen) return <ReceiptDrawer item={item} onClose={() => { setReceiptOpen(false); onAttachmentsChanged?.() }} onChanged={() => onAttachmentsChanged?.()}/>
  return <Drawer canClose={!busy} title={item.is_cancelled ? 'Удалённый платёж' : mode === 'details' ? 'Карточка платежа' : item.status === 'paid' ? 'Изменить оплату' : 'Отметить оплату'} subtitle={mode === 'payment' ? 'Укажите дату уже выполненной оплаты.' : 'Условия, оплата и история платежа.'} onClose={() => { if (!guard.current) onClose() }}>
    <div className="payment-editor">
      <section className="payment-detail" aria-label="Условия периода">
        <h3 className="payment-title">{item.title}</h3>
        <dl>
          <div><dt>Сумма</dt><dd>{money(item.amount, item.currency)}</dd></div>
          <div><dt>Срок оплаты</dt><dd>{dateLabel(item.due_date)}</dd></div>
          <div><dt>Статус</dt><dd><PaymentStatus item={item}/></dd></div>
          {mode === 'details' && <div><dt>Повторение</dt><dd>{item.periodicity === 'once' ? 'Разовый платёж' : item.recurring_payment_is_active ? recurrenceLabel(item.periodicity || 'monthly', item.recurrence_interval) : 'Прекращено'}</dd></div>}
          {mode === 'details' && item.paid_on && <div><dt>Дата оплаты</dt><dd>{dateLabel(item.paid_on)}</dd></div>}
          {item.days_late > 0 && <div><dt>Дней опоздания</dt><dd>{item.days_late}</dd></div>}
        </dl>
        {item.amount_is_custom && <p className="amount-custom-note">Индивидуальная сумма и валюта этого периода</p>}
        {item.periodicity !== 'once' && !item.recurring_payment_is_active && !item.is_cancelled && <div className="notice"><Info size={18}/><p>Регулярный платёж прекращён. Этот период сохранён в истории, его оплату можно исправить.</p></div>}
      </section>
      {error ? <ErrorNotice error={error}/> : null}
      {!item.is_cancelled && mode === 'payment' && <form className="payment-form" noValidate onSubmit={(event: FormEvent) => { event.preventDefault(); void save(true) }}>
        <div className="field">
          <label htmlFor="paid-on">Фактическая дата оплаты</label>
          <DatePicker name="paid_on" id="paid-on" today={today} aria-label="Фактическая дата оплаты" required max={today} value={paidOn} onChange={value => { paidOnEdited.current = true; setPaidOn(value) }} disabled={busy || loading} aria-invalid={Boolean(fieldError)} aria-describedby={fieldError ? 'paid-on-hint paid-on-error' : 'paid-on-hint'}/>
          <small id="paid-on-hint">Досрочная оплата разрешена. Сегодня ({timezone}): {dateLabel(today)}.</small>
          {fieldError && <span id="paid-on-error" className="field-error" role="alert">{fieldError}</span>}
        </div>
        <div className="notice payment-confirmation-note"><Info size={18}/><p>Это отметка для учёта: деньги не списываются. Срок платежа остаётся прежним.</p></div>
        <div className="payment-action-layout">
          <div className="form-actions payment-actions">
            <button className="btn btn-primary" type="submit" disabled={busy || loading}>{busy ? <span className="spinner"/> : <Check size={17}/>}<span>{item.status === 'paid' ? 'Сохранить дату' : 'Подтвердить оплату'}</span></button>
            {item.status === 'paid' && <button className="btn btn-danger" type="button" disabled={busy || loading} onClick={() => void save(false)}>Отменить отметку оплаты</button>}
          </div>
          <div className="payment-secondary-actions">
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => changeMode('details')}>К карточке платежа</button>
          </div>
        </div>
      </form>}
      {!item.is_cancelled && mode === 'details' && <div className="payment-action-layout">
        <button className="btn btn-primary" type="button" disabled={loading} onClick={() => changeMode('payment')}>{item.status === 'paid' ? 'Дата и отметка оплаты' : 'Отметить оплату'}</button>
        <div className="payment-secondary-actions">
          {onEdit && <button type="button" className="btn btn-secondary" disabled={loading} onClick={() => onEdit(item)}><PencilLine size={16}/>Редактировать платёж</button>}
          <button type="button" className="btn btn-secondary" onClick={onHistory}><History size={16}/>История платежа</button>
          <button type="button" className="btn btn-secondary" onClick={() => setReceiptOpen(true)}><Paperclip size={16}/>Чек или ссылка</button>
          {onDelete && item.status === 'unpaid' && <button type="button" className="btn btn-danger" disabled={loading} onClick={() => onDelete(item)}><Trash2 size={16}/>Удалить платёж</button>}
        </div>
      </div>}
      {item.is_cancelled && <p className="notice">Период удалён из обязательств и доступен только для просмотра.</p>}
      {item.is_cancelled && <div className="payment-secondary-actions"><button type="button" className="btn btn-secondary" onClick={() => setReceiptOpen(true)}><Paperclip size={16}/><span>Чек или ссылка</span></button></div>}
    </div>
  </Drawer>
}


export function PaymentsView({ isAdmin, mode, route, onRouteChange, revision, today, timezone, selectedRule, onHistory, onChanged, notify }: Props) {
  const history = mode === 'history'
  const { filters, offset, limit } = route
  const [page, setPage] = useState<Page<PaymentOccurrence> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  const [selected, setSelected] = useState<PaymentOccurrence | null>(null)
  const [selectedMode, setSelectedMode] = useState<'details' | 'payment'>('details')
  const [deleteTarget, setDeleteTarget] = useState<PaymentOccurrence | null>(null)
  const [editTarget, setEditTarget] = useState<PaymentOccurrence | null>(null)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const lastQuery = useRef('')
  const query = useMemo<OccurrenceFilters>(() => ({ date_from: filters.date_from || undefined, date_to: filters.date_to || undefined, currency: filters.currency as Currency || undefined, status: filters.tab === 'paid' ? 'paid' : ['unpaid','overdue'].includes(filters.tab) ? 'unpaid' : undefined, is_overdue: filters.tab === 'overdue' ? true : undefined, recurring_payment_id: route.ruleId || undefined,
    include_cancelled: history && filters.include_cancelled || undefined, limit, offset }), [filters, route.ruleId, limit, offset, history])
  const summaryDates = useMemo(() => ({ date_from: filters.date_from, date_to: filters.date_to }), [filters.date_from, filters.date_to])
  useEffect(() => {
    let alive = true
    const key = JSON.stringify(query)
    if (lastQuery.current !== key) setPage(null)
    lastQuery.current = key
    setLoading(true); setError(null)
    api.listOccurrences(query).then(value => {
      if (!alive) return
      if (offset > 0 && value.items.length === 0 && value.total <= offset) {
        onRouteChange({ ...route, offset: Math.floor(Math.max(0, value.total - 1) / limit) * limit }, true)
        return
      }
      setPage(value)
    }).catch(reason => { if (alive) setError(reason) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [query, revision, retry, offset, limit, onRouteChange, route])
  function editPayment(item: PaymentOccurrence) { setSelected(null); setEditTarget(item) }
  function openPayment(item: PaymentOccurrence, mode: 'details' | 'payment') { setSelectedMode(mode); setSelected(item) }
  function applyFilters(next: PaymentFilters) { onRouteChange({ ...route, filters: next, offset: 0 }) }
  function resetFilters() { onRouteChange({ ...route, filters: defaultPaymentFilters(mode, today), offset: 0, ruleId: null }) }
  function tab(value: PaymentTab) { applyFilters({ ...filters, tab: value }) }
  function saved(item: PaymentOccurrence) {
    setPage(previous => previous ? { ...previous, items: previous.items.map(row => row.id === item.id ? item : row) } : previous)
    setSelected(null); onChanged(); notify(item.status === 'unpaid' ? 'Отметка оплаты отменена. Дата оплаты очищена.' : item.paid_late ? 'Оплата сохранена. Период оплачен с опозданием.' : 'Оплата сохранена. Срок не изменился.')
  }
  return <>
    {!history && <OverdueNotice revision={revision} today={today} timezone={timezone} limit={limit}/>}
    {!history && <Summary dates={summaryDates} revision={revision} filters={filters} limit={limit} today={today} timezone={timezone}/>}
    <section id="payment-results" className="panel" aria-label={history ? 'История периодов' : 'Периоды оплаты'} aria-busy={loading}>
      <div className="section-head"><div><h2 id="payment-results-heading" tabIndex={-1}>{history ? 'Все периоды' : 'Периоды оплаты'}{page && <span className="pill">{page.total}</span>}</h2><p>{history ? 'Сохраняем прошлые оплаты и периоды прекращённых платежей.' : 'Откройте название для подробностей или выберите действие в строке.'}</p></div><button className="icon-button" type="button" aria-label="Обновить список и сводку" disabled={loading} onClick={() => { setRetry(value => value + 1); onChanged() }}><RefreshCw size={17}/></button></div>
      {selectedRule && <div className="history-chip"><History size={16}/><strong>{page?.items[0]?.title || selectedRule.title}</strong><button type="button" className="btn btn-secondary btn-small" onClick={() => onRouteChange({ ...route, ruleId: null, offset: 0 })}>Все платежи</button></div>}
      <div className="status-tabs" role="group" aria-label="Фильтр статуса">{([['all','Все'],['unpaid','К оплате'],['overdue','Просрочено'],['paid','Оплачено']] as const).map(([value,label]) => <button className={`status-tab ${filters.tab === value ? 'active' : ''}`} type="button" aria-pressed={filters.tab === value} key={value} onClick={() => tab(value)}>{label}</button>)}</div>
      <div className="mobile-filter-control"><button className="btn btn-secondary payment-filter-toggle" type="button" aria-label="Фильтры периода и валюты" aria-expanded={filtersOpen} aria-controls="payment-filters" onClick={() => setFiltersOpen(value => !value)}>Период и валюта<ChevronDown size={16} aria-hidden="true"/></button><p>{[filters.date_from && `С ${dateLabel(filters.date_from)}`, filters.date_to && `по ${dateLabel(filters.date_to)}`].filter(Boolean).join(' ') || 'За всё время'} · {filters.currency || 'Все валюты'}</p></div>
      <div id="payment-filters" className="payment-filters" data-open={filtersOpen}><PaymentFilterToolbar key={JSON.stringify(filters)} filters={filters} today={today} history={history} onApply={applyFilters} onReset={resetFilters}/></div>
      {error ? <ErrorNotice error={error} onRetry={() => setRetry(value => value + 1)}/> : null}
      {loading && !page ? <LoadingRows/> : !error && page?.items.length === 0 ? <EmptyState title="Платежей не найдено">Попробуйте изменить даты или сбросить фильтры. Прекращённые платежи остаются в истории.</EmptyState> : page && <div className="table-wrap"><table className="data-table payments-table"><caption className="sr-only">{history ? 'История платежных периодов' : 'Платежи за выбранный период'}</caption><colgroup><col className="payment-name-column"/><col className="payment-money-column"/><col className="payment-due-column"/><col className="payment-status-column"/><col className="payment-paid-column"/><col className="payment-actions-column"/></colgroup><thead><tr><th scope="col">Платёж</th><th scope="col">Сумма</th><th scope="col">Срок</th><th scope="col">Статус</th><th scope="col">Дата оплаты</th><th scope="col">Действия</th></tr></thead><tbody>{page.items.map(item => {
        const frequency = item.periodicity === 'monthly' && (item.recurrence_interval ?? 1) === 1 ? 'ежемесячный' : recurrenceLabel(item.periodicity || 'monthly', item.recurrence_interval).toLocaleLowerCase('ru')
        return <tr key={item.id}><td data-label="Платёж"><button className="payment-title" type="button" onClick={() => openPayment(item, 'details')}>{item.title}</button><span className="payment-period">{monthLabel(item.due_date.slice(0,7))}{item.periodicity === 'once' ? ' · разовый' : !item.recurring_payment_is_active ? ' · прекращён' : ` · ${frequency}`}{item.is_cancelled && ' · удалён'}</span></td><td data-label="Сумма" className={item.amount.split('.')[0].length > 9 ? 'money-large' : ''}><span className="money">{money(item.amount, item.currency)}</span></td><td data-label="Срок" className="date-cell">{dateLabel(item.due_date)}</td><td data-label="Статус" className="payment-status-cell"><PaymentStatus item={item}/>{!item.is_cancelled && item.days_late > 0 && <span className="payment-period">Опоздание: {item.days_late} дн.</span>}</td><td data-label="Дата оплаты" className="date-cell payment-paid-cell">{dateLabel(item.paid_on)}</td><td data-label="Действия"><div className="inline-actions payment-row-actions"><button className={`btn btn-small ${!item.is_cancelled && item.status === 'unpaid' ? 'btn-primary' : 'btn-secondary'}`} type="button" onClick={() => openPayment(item, item.is_cancelled ? 'details' : 'payment')}>{item.is_cancelled ? 'Посмотреть' : item.status === 'paid' ? 'Дата оплаты' : 'Отметить оплату'}</button>{isAdmin && !item.is_cancelled && <button className="btn btn-secondary btn-small" type="button" aria-label={`Редактировать платёж: ${item.title}`} onClick={() => editPayment(item)}>Редактировать</button>}{isAdmin && !item.is_cancelled && item.status === 'unpaid' && <button className="icon-button danger-text" type="button" aria-label={`Удалить платёж: ${item.title}`} title="Удалить платёж" onClick={() => setDeleteTarget(item)}><Trash2 size={16}/></button>}</div></td></tr>
      })}</tbody></table></div>}
      {page && !error && <><div className="page-size"><label htmlFor="page-size">На странице</label><SelectField id="page-size" className="ik-select-compact" value={String(limit)} onChange={size => onRouteChange({ ...route, limit: Number(size) as PaymentPageSize, offset: 0 })} options={[6, 12, 24].map(size => ({ value: String(size), label: String(size) }))}/></div><Pagination total={page.total} limit={limit} offset={offset} onPage={nextOffset => onRouteChange({ ...route, offset: nextOffset })}/></>}
    </section>
    <div className="footer-note"><span><Send size={14}/> Напоминание в Telegram — за 3 дня до срока</span><span><Clock3 size={14}/> Часовой пояс: {timezone}</span></div>
    {history && <label className="section-note"><input type="checkbox" checked={Boolean(filters.include_cancelled)} onChange={event => onRouteChange({ ...route, filters: { ...filters, include_cancelled: event.target.checked }, offset: 0 })}/> Показать удалённые периоды</label>}
    {history && <p className="summary-caption"><Info size={14}/> Прекращение повторения не отменяет уже возникшие обязательства и не удаляет историю.</p>}
    {deleteTarget && <DeletePaymentDrawer target={{ kind: "period", item: deleteTarget }} onClose={() => { setDeleteTarget(null); onChanged() }} onDeleted={() => { setDeleteTarget(null); onChanged(); notify("Платёж удалён из обязательств. История сохранена.") }}/>}
    {editTarget && <PaymentEditDrawer key={`period:${editTarget.id}`} target={{ ...editTarget, kind: 'period', dueDate: editTarget.due_date }} onSave={async values => { await api.updateOccurrenceDetails(editTarget.id, values) }} onSaved={() => { setEditTarget(null); onChanged(); notify('Изменения платежа сохранены.') }} onClose={refresh => { setEditTarget(null); if (refresh) onChanged() }}/>}
    {selected && <PaymentDrawer key={selected.id} initial={selected} initialMode={selectedMode} today={today} timezone={timezone} onAttachmentsChanged={onChanged} onDelete={isAdmin ? item => { setSelected(null); setDeleteTarget(item) } : undefined} onEdit={isAdmin ? editPayment : undefined} onClose={() => setSelected(null)} onSaved={saved} onHistory={() => { setSelected(null); onHistory(selected.recurring_payment_id, selected.title) }}/>}
  </>
}
