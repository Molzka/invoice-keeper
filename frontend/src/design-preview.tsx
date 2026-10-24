import { StrictMode, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Brand } from './components/Brand'
import { ThemeControl } from './components/ThemeControl'
import { BudgetPanel } from './components/BudgetPanel'
import type { BudgetPeriod, BudgetReport, BudgetTotals } from './components/BudgetPanel'
import { ReceiptsPanel } from './components/ReceiptsPanel'
import type { ReceiptEntry, ReceiptFilters } from './components/ReceiptsPanel'
import type { Currency } from './types/api'
import { createFixtures, DEMO_TODAY } from './mocks/fixtures'
import './styles.css'
import './styles/visual-refresh.css'
import './styles/fields.css'
import './styles/date-picker.css'
import './styles/motion.css'
import './styles/workspace-art.css'
import './styles/button-polish.css'
import './styles/budget.css'
import './styles/receipts.css'
import './styles/brand-tokens.css'
import './styles/theme.css'
import './styles/brand-identity.css'

const fixtures = createFixtures()
const currencies: Currency[] = ['RUB', 'USD', 'EUR']
const minor = (value: string) => BigInt(value.replace('.', ''))
const decimal = (value: bigint) => String(value / 100n) + '.' + String(value % 100n).padStart(2, '0')
function totals(from: string, to: string): Record<Currency, BudgetTotals> {
  return Object.fromEntries(currencies.map(currency => {
    const rows = fixtures.occurrences.filter(item => item.currency === currency && item.due_date >= from && item.due_date <= to)
    const sum = (key: 'all' | 'paid' | 'unpaid' | 'overdue') => decimal(rows.filter(row => key === 'all' || (key === 'overdue' ? row.is_overdue : row.status === key)).reduce((total, row) => total + minor(row.amount), 0n))
    return [currency, { planned: sum('all'), paid: sum('paid'), unpaid: sum('unpaid'), overdue: sum('overdue') }]
  })) as Record<Currency, BudgetTotals>
}
function monthBounds(year: number, month: number) {
  const value = String(year).padStart(4, '0') + '-' + String(month).padStart(2, '0')
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const last = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
  return { date_from: value + '-01', date_to: value + '-' + last }
}
const receipts: ReceiptEntry[] = fixtures.occurrences.filter(item => item.due_date.startsWith(DEMO_TODAY.slice(0, 7))).map((item, index) => ({ ...item, occurrence_id: item.id, can_edit: false, attachments: index % 3 === 0 ? [{ id: item.id + '-link', kind: 'link', url: 'https://example.com', label: 'Демонстрационная ссылка' }] : index % 3 === 1 ? [{ id: item.id + '-file', kind: 'file', url: '', label: 'Образец чека', file_name: 'receipt-demo.pdf', size_bytes: 148500 }] : [] }))

export function DesignPreview() {
  const [page, setPage] = useState<'budget' | 'receipts'>('budget')
  const [period, setPeriod] = useState<BudgetPeriod>({ mode: 'year', year: Number(DEMO_TODAY.slice(0, 4)), month: Number(DEMO_TODAY.slice(5, 7)) })
  const [filters, setFilters] = useState<ReceiptFilters>({ query: '', currency: '', kind: 'all' })
  const [offset, setOffset] = useState(0)
  const report = useMemo<BudgetReport>(() => {
    const dates = period.mode === 'month' ? monthBounds(period.year, period.month) : { date_from: String(period.year).padStart(4, '0') + '-01-01', date_to: String(period.year).padStart(4, '0') + '-12-31' }
    return { ...dates, as_of_date: DEMO_TODAY, totals: totals(dates.date_from, dates.date_to), months: period.mode === 'year' ? Array.from({ length: 12 }, (_, i) => { const bounds = monthBounds(period.year, i + 1); return { month: bounds.date_from.slice(0, 7), totals: totals(bounds.date_from, bounds.date_to) } }) : undefined }
  }, [period])
  const filtered = receipts.filter(item => (!filters.query || item.title.toLocaleLowerCase('ru').includes(filters.query.toLocaleLowerCase('ru'))) && (!filters.currency || item.currency === filters.currency) && (filters.kind === 'all' || filters.kind === 'missing' && !item.attachments.length || item.attachments.some(attachment => attachment.kind === filters.kind)))
  return <div className="app-shell"><header className="topbar"><div className="brand-slot"><Brand onHome={() => setPage('budget')}/></div><div className="user-menu"><ThemeControl/></div><p style={{ margin: 0, fontSize: 12 }}>Просмотр оформления · демонстрационные данные · API ещё не подключён</p><nav className="main-nav" aria-label="Просмотр новых разделов"><button className={`nav-link ${page === 'budget' ? 'active' : ''}`} onClick={() => setPage('budget')}>Бюджет</button><button className={`nav-link ${page === 'receipts' ? 'active' : ''}`} onClick={() => setPage('receipts')}>Чеки и ссылки</button><a className="nav-link" href="/">Открыть приложение</a></nav></header><main className="app-main">{page === 'budget' ? <BudgetPanel period={period} onPeriodChange={setPeriod} report={report} loading={false} error={null} onRetry={() => {}}/> : <ReceiptsPanel items={filtered.slice(offset, offset + 6)} filters={filters} onFiltersChange={value => { setFilters(value); setOffset(0) }} loading={false} onRetry={() => {}} total={filtered.length} limit={6} offset={offset} onPage={setOffset} eyebrow="Просмотр дизайна"/>}</main></div>
}
if (import.meta.env.DEV) createRoot(document.getElementById('root')!).render(<StrictMode><DesignPreview/></StrictMode>)
