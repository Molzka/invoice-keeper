import { useId, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Currency } from '../types/api'
import { dateLabel, money } from '../lib/format'
import { ArrowUpRight, ChevronLeft, ChevronRight, Info, Wallet } from './BrandIcons'
import { PageHeader } from './PageHeader'
import { SelectField } from './SelectField'
import { EmptyState, ErrorNotice } from './UI'

export interface BudgetPeriod {
  mode: 'month' | 'year'
  year: number
  month: number
}

export interface BudgetTotals {
  planned: string
  paid: string
  unpaid: string
  overdue: string
  forecast?: string
}

export interface BudgetReport {
  date_from: string
  date_to: string
  as_of_date: string
  timezone?: string
  totals: Record<Currency, BudgetTotals>
  months?: Array<{ month: string; totals: Record<Currency, BudgetTotals> }>
}

export interface BudgetOpenPaymentsQuery {
  date_from: string
  date_to: string
  currency: Currency
  status: 'all' | 'paid' | 'unpaid' | 'overdue'
}

export interface BudgetPanelProps {
  period: BudgetPeriod
  onPeriodChange: (period: BudgetPeriod) => void
  report: BudgetReport | null
  loading: boolean
  error: unknown
  onRetry: () => void
  onOpenPayments?: (query: BudgetOpenPaymentsQuery) => void
}

const currencies: Currency[] = ['RUB', 'USD', 'EUR']
const currencyLabels: Record<Currency, string> = { RUB: 'Рубли', USD: 'Доллары', EUR: 'Евро' }
const currencySymbols: Record<Currency, string> = { RUB: '₽', USD: '$', EUR: '€' }
const monthLabels = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
const shortMonthLabels = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн', 'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

/** Exact decimal amounts become integer minor units; only the final bounded ratio uses Number. */
function minorUnits(value: string): bigint | null {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,2})?$/.test(value)) return null
  const [whole, fraction = ''] = value.split('.')
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
}

function percent(part: bigint, total: bigint): number {
  if (total <= 0n || part <= 0n) return 0
  return Number((part > total ? total : part) * 10000n / total) / 100
}

function validTotals(totals: Record<Currency, BudgetTotals>): boolean {
  return currencies.every(currency => totals?.[currency] && ['planned', 'paid', 'unpaid', 'overdue', 'forecast'].every(key => minorUnits(totals[currency][key as keyof BudgetTotals] ?? '0.00') !== null))
}

function monthDates(value: string) {
  const [year, month] = value.split('-').map(Number)
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const lastDay = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
  return { date_from: `${value}-01`, date_to: `${value}-${lastDay}` }
}

function monthName(value: string, abbreviated = false) {
  const month = Number(value.slice(5, 7)) - 1
  return (abbreviated ? shortMonthLabels : monthLabels)[month] ?? value
}

function BudgetLoading() {
  return <div className="budget-loading" role="status" aria-label="Загрузка бюджета" aria-busy="true"><span className="sr-only">Загружаем итоги за выбранный период…</span><div className="budget-cards">{currencies.map(currency => <div className="budget-currency-card" key={currency}><div className="skeleton" style={{ width: '40%', height: 18 }}/><div className="skeleton" style={{ height: 40, margin: '24px 0' }}/><div className="skeleton" style={{ height: 110 }}/></div>)}</div><div className="budget-chart-skeleton skeleton"/></div>
}

function AmountAction({ amount, currency, label, status, dates, onOpenPayments, className = '' }: {
  amount: string
  currency: Currency
  label: string
  status: BudgetOpenPaymentsQuery['status']
  dates: { date_from: string; date_to: string }
  onOpenPayments?: BudgetPanelProps['onOpenPayments']
  className?: string
}) {
  const text = money(amount, currency)
  if (!onOpenPayments) return <span className={`budget-amount-value ${className}`}>{text}</span>
  return <button type="button" className={`budget-amount-action ${className}`} aria-label={`${label}, ${currency}: ${text}. Открыть платежи`} onClick={() => onOpenPayments({ ...dates, currency, status })}><span>{text}</span><ArrowUpRight size={13} aria-hidden="true"/></button>
}

function CurrencyBudget({ currency, totals, dates, onOpenPayments }: { currency: Currency; totals: BudgetTotals; dates: { date_from: string; date_to: string }; onOpenPayments?: BudgetPanelProps['onOpenPayments'] }) {
  const planned = minorUnits(totals.planned)!
  const paid = minorUnits(totals.paid)!
  const paidPercent = percent(paid, planned)
  return <article className="budget-currency-card" data-currency={currency}>
    <span className="budget-currency-watermark" aria-hidden="true">{currencySymbols[currency]}</span>
    <div className="budget-currency-title"><h2>{currencyLabels[currency]}</h2><span>{currency}</span></div>
    <p className="budget-total-label">Всего с прогнозом</p>
    <div className="budget-total"><AmountAction amount={totals.planned} currency={currency} label="Все обязательства" status="all" dates={dates} onOpenPayments={onOpenPayments}/></div>
    <div className="budget-progress-copy"><span>Оплачено от общего</span><strong>{paidPercent.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%</strong></div>
    <div className="budget-progress" aria-hidden="true"><span style={{ width: `${paidPercent}%` }}/></div>
    <dl className="budget-breakdown">
      <div><dt><span className="budget-key budget-key-paid" aria-hidden="true"/>Оплачено</dt><dd><AmountAction amount={totals.paid} currency={currency} label="Оплачено" status="paid" dates={dates} onOpenPayments={onOpenPayments}/></dd></div>
      <div><dt><span className="budget-key budget-key-unpaid" aria-hidden="true"/>Не оплачено</dt><dd><AmountAction amount={totals.unpaid} currency={currency} label="Не оплачено" status="unpaid" dates={dates} onOpenPayments={onOpenPayments}/></dd></div>
      <div className="budget-overdue"><dt>Из них просрочено</dt><dd><AmountAction amount={totals.overdue} currency={currency} label="Просрочено" status="overdue" dates={dates} onOpenPayments={onOpenPayments}/></dd></div>
      <div><dt><span className="budget-key budget-key-forecast" aria-hidden="true"/>Прогноз будущих сроков</dt><dd>{money(totals.forecast ?? "0.00", currency)}</dd></div>
    </dl>
  </article>
}

function AnnualOverview({ months, year, onPeriodChange, onOpenPayments }: { months: NonNullable<BudgetReport['months']>; year: number; onPeriodChange: BudgetPanelProps['onPeriodChange']; onOpenPayments?: BudgetPanelProps['onOpenPayments'] }) {
  const [currency, setCurrency] = useState<Currency>('RUB')
  const headingId = useId()
  const maxAmount = months.reduce((max, month) => {
    const value = minorUnits(month.totals[currency].planned)!
    return value > max ? value : max
  }, 0n)
  return <section className="budget-annual panel" aria-labelledby={headingId}>
    <div className="budget-annual-head"><div><p className="budget-section-eyebrow">Год в деталях</p><h2 id={headingId}>По месяцам</h2><p>Нажмите на месяц, чтобы открыть его бюджет.</p></div><div className="budget-currency-switch" role="group" aria-label="Валюта помесячного обзора">{currencies.map(value => <button key={value} type="button" aria-pressed={currency === value} onClick={() => setCurrency(value)}>{value}</button>)}</div></div>
    {months.length === 0 ? <EmptyState title="Помесячных данных пока нет">Итоги за год показаны выше. Детализация появится после расчёта на сервере.</EmptyState> : <>
      <div className="budget-chart-legend"><span><i className="budget-key budget-key-paid"/>Оплачено</span><span><i className="budget-key budget-key-unpaid"/>Не оплачено</span><span><i className="budget-key budget-key-forecast"/>Прогноз</span><span><i className="budget-key budget-key-overdue"/>Из них просрочено</span></div>
      <div className="budget-chart-scroll"><div className="budget-chart" style={{ '--budget-month-count': months.length } as CSSProperties} aria-label={`Обязательства по месяцам, ${currency}`}>
        {months.map((month, index) => {
          const total = month.totals[currency]
          const planned = minorUnits(total.planned)!
          const paid = minorUnits(total.paid)!
          const unpaid = minorUnits(total.unpaid)!
          const overdue = minorUnits(total.overdue)!
          const overduePart = overdue > unpaid ? unpaid : overdue
          return <button className="budget-chart-month" type="button" key={`${month.month}:${currency}`} style={{ '--budget-column-order': index } as CSSProperties} onClick={() => onPeriodChange({ mode: 'month', year: Number(month.month.slice(0, 4)), month: Number(month.month.slice(5, 7)) })} aria-label={`${monthName(month.month)} ${year}, всего ${money(total.planned, currency)}, оплачено ${money(total.paid, currency)}, не оплачено ${money(total.unpaid, currency)}, из них просрочено ${money(total.overdue, currency)}. Открыть бюджет месяца`}>
            <span className="budget-chart-column" aria-hidden="true"><span className="budget-chart-fill" data-empty={planned === 0n} style={{ height: `${percent(planned, maxAmount)}%` }}><span className="budget-chart-forecast" style={{ height: `${percent(minorUnits(total.forecast ?? "0.00")!, planned)}%` }}/><span className="budget-chart-paid" style={{ height: `${percent(paid, planned)}%` }}/><span className="budget-chart-overdue" style={{ height: `${percent(overduePart, planned)}%`, top: "auto", bottom: `${percent(paid, planned)}%` }}/></span><span className="budget-chart-tooltip">{money(total.planned, currency)}</span></span><span className="budget-chart-label" aria-hidden="true">{monthName(month.month, true)}</span>
          </button>
        })}
      </div></div>
      <div className="budget-month-table-wrap"><table className="budget-month-table"><caption className="sr-only">Точные суммы бюджета по месяцам в {currency}</caption><thead><tr><th scope="col">Месяц</th><th scope="col">Всего по срокам</th><th scope="col">Оплачено</th><th scope="col">Не оплачено</th><th scope="col">Из них просрочено</th><th scope="col">Прогноз</th></tr></thead><tbody>{months.map(month => <tr key={month.month}><th scope="row"><button type="button" className="budget-month-name" onClick={() => onPeriodChange({ mode: 'month', year: Number(month.month.slice(0, 4)), month: Number(month.month.slice(5, 7)) })}>{monthName(month.month)}<ArrowUpRight size={13}/></button></th>{(['planned', 'paid', 'unpaid', 'overdue'] as const).map((key, index) => <td key={key} data-label={['Всего по срокам', 'Оплачено', 'Не оплачено', 'Из них просрочено'][index]} className={key === 'overdue' ? 'budget-table-overdue' : undefined}><AmountAction amount={month.totals[currency][key]} currency={currency} label={`${monthName(month.month)}: ${['Все обязательства', 'Оплачено', 'Не оплачено', 'Просрочено'][index]}`} status={key === 'planned' ? 'all' : key} dates={monthDates(month.month)} onOpenPayments={onOpenPayments}/></td>)}<td data-label="Прогноз">{money(month.totals[currency].forecast ?? "0.00", currency)}</td></tr>)}</tbody></table></div>
    </>}
    <p className="budget-annual-footnote">Валюты показаны отдельно. График дополняет точные суммы в таблице.</p>
  </section>
}

export function BudgetPanel({ period, onPeriodChange, report, loading, error, onRetry, onOpenPayments }: BudgetPanelProps) {
  const monthId = useId()
  const yearId = useId()
  const yearOptions = Array.from({ length: Math.min(9999, period.year + 10) - Math.max(1, period.year - 10) + 1 }, (_, index) => {
    const year = Math.max(1, period.year - 10) + index
    return { value: String(year), label: String(year) }
  })
  const canPrevious = period.year > 1 || period.mode === 'month' && period.month > 1
  const canNext = period.year < 9999 || period.mode === 'month' && period.month < 12
  function movePeriod(direction: -1 | 1) {
    if (direction === -1 && !canPrevious || direction === 1 && !canNext) return
    if (period.mode === 'year') { onPeriodChange({ ...period, year: period.year + direction }); return }
    const month = period.month + direction
    onPeriodChange({ ...period, year: month < 1 ? period.year - 1 : month > 12 ? period.year + 1 : period.year, month: month < 1 ? 12 : month > 12 ? 1 : month })
  }
  const valid = report && validTotals(report.totals) && (report.months ?? []).every(month => /^\d{4}-(?:0[1-9]|1[0-2])$/.test(month.month) && validTotals(month.totals))
  return <div className="budget-page">
    <PageHeader kind="budget" title="Бюджет" eyebrow="Рабочее пространство" description="Обязательства на месяц и год. Полная картина по каждой валюте."/>
    <section className="budget-period-controls" aria-label="Период бюджета"><div className="budget-period-mode" role="group" aria-label="Масштаб бюджета"><button type="button" aria-pressed={period.mode === 'month'} onClick={() => onPeriodChange({ ...period, mode: 'month' })}>Месяц</button><button type="button" aria-pressed={period.mode === 'year'} onClick={() => onPeriodChange({ ...period, mode: 'year' })}>Год</button></div><div className="budget-period-fields">{period.mode === 'month' && <div className="budget-period-field"><label htmlFor={monthId}>Месяц</label><SelectField id={monthId} value={String(period.month)} options={monthLabels.map((label, index) => ({ value: String(index + 1), label }))} onChange={value => onPeriodChange({ ...period, month: Number(value) })}/></div>}<div className="budget-period-field budget-year-field"><label htmlFor={yearId}>Год</label><SelectField id={yearId} value={String(period.year)} options={yearOptions} onChange={value => onPeriodChange({ ...period, year: Number(value) })}/></div><div className="budget-period-arrows"><button type="button" className="icon-button" disabled={!canPrevious} aria-label={period.mode === 'month' ? 'Предыдущий месяц' : 'Предыдущий год'} onClick={() => movePeriod(-1)}><ChevronLeft size={18}/></button><button type="button" className="icon-button" disabled={!canNext} aria-label={period.mode === 'month' ? 'Следующий месяц' : 'Следующий год'} onClick={() => movePeriod(1)}><ChevronRight size={18}/></button></div></div></section>
    {error ? <ErrorNotice error={error} onRetry={onRetry}/> : loading ? <BudgetLoading/> : !report ? <div className="budget-empty panel"><EmptyState title="За этот период пока нет данных">Выберите другой месяц или год либо повторите загрузку.</EmptyState><button type="button" className="btn btn-secondary" onClick={onRetry}>Повторить загрузку</button></div> : !valid ? <ErrorNotice error={new Error('Сервер вернул некорректные суммы бюджета. Повторите загрузку.')} onRetry={onRetry}/> : <>
      <div className="budget-report-caption"><div><Wallet size={15} aria-hidden="true"/><span>По срокам {dateLabel(report.date_from)}–{dateLabel(report.date_to)}</span></div><span>Состояние на {dateLabel(report.as_of_date)}, {report.timezone || "Europe/Moscow"}</span></div>
      {onOpenPayments && <p className="budget-drilldown-hint"><ArrowUpRight size={13} aria-hidden="true"/>Нажмите на сумму, чтобы открыть соответствующие платежи</p>}
      <div className="budget-cards">{currencies.map(currency => <CurrencyBudget key={currency} currency={currency} totals={report.totals[currency]} dates={report} onOpenPayments={onOpenPayments}/>)}</div>
      {period.mode === 'year' && <AnnualOverview key={period.year} months={report.months ?? []} year={period.year} onPeriodChange={onPeriodChange} onOpenPayments={onOpenPayments}/>}
      <p className="budget-data-note"><Info size={16} aria-hidden="true"/><span>Итоги рассчитаны сервером: всего = оплачено + не оплачено + прогноз. Прогноз — будущие сроки, для которых ещё нет сохранённого периода; он не создаёт платежи или напоминания. Нажатие на сумму открывает только существующие периоды. Суммы RUB, USD и EUR не складываются между собой и не конвертируются.</span></p>
    </>}
  </div>
}
