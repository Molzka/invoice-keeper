export type WorkspaceView = 'payments' | 'history' | 'recurring' | 'users' | 'calendar' | 'activity'
export type PaymentTab = 'all' | 'unpaid' | 'overdue' | 'paid'
export type PaymentCurrency = '' | 'RUB' | 'USD' | 'EUR'
export type PaymentFilters = {
  date_from: string
  date_to: string
  currency: PaymentCurrency
  tab: PaymentTab
}
export type PaymentPageSize = 6 | 12 | 24
export type PaymentRoute = {
  view: WorkspaceView
  filters: PaymentFilters
  limit: PaymentPageSize
  offset: number
  ruleId: string | null
}
export type PaymentRouteOptions = {
  limit?: number
  offset?: number
  ruleId?: string | null
}

const views: readonly string[] = ['payments', 'history', 'recurring', 'users', 'calendar', 'activity']
const tabs: readonly string[] = ['all', 'unpaid', 'overdue', 'paid']
const currencies: readonly string[] = ['RUB', 'USD', 'EUR']
const pageSizes: readonly number[] = [6, 12, 24]
const maxOffset = 1_000_000

/** Validate calendar dates without parsing through a browser timezone. */
function calendarDate(value: string | null): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return ''
  const [year, month, day] = value.split('-').map(Number)
  if (year < 1 || month < 1 || month > 12 || day < 1) return ''
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return day <= days[month - 1] ? value : ''
}

function monthBounds(today: string) {
  if (!calendarDate(today)) throw new RangeError('today must be a valid YYYY-MM-DD calendar date')
  const month = today.slice(0, 7)
  const [year, number] = today.split('-').map(Number)
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return { date_from: `${month}-01`, date_to: `${month}-${days[number - 1]}` }
}

function safeOffset(value: number): number {
  return Number.isSafeInteger(value) && value >= 0 ? Math.min(value, maxOffset) : 0
}

function queryInteger(value: string | null): number {
  return value !== null && /^\d+$/.test(value) ? Number(value) : Number.NaN
}

function pageSize(value: number): PaymentPageSize {
  return pageSizes.includes(value) ? value as PaymentPageSize : 6
}

function ruleSelection(value: string | null | undefined): string | null {
  if (!value) return null
  const clean = Array.from(value).filter(character => {
    const code = character.codePointAt(0) ?? 0
    return code > 31 && (code < 127 || code > 159)
  }).join('').trim()
  return clean.length > 0 && clean.length <= 200 ? clean : null
}

/** Empty history dates mean the entire history; payments require a bounded summary. */
export function defaultPaymentFilters(view: WorkspaceView, today: string): PaymentFilters {
  return {
    ...(view === 'history' ? { date_from: '', date_to: '' } : monthBounds(today)),
    currency: '',
    tab: 'all',
  }
}

/** Parse an SPA hash into validated state. Unknown query keys never reach the API. */
export function readPaymentRoute(hash: string, today: string): PaymentRoute {
  const value = hash.replace(/^#/, '')
  const separator = value.indexOf('?')
  const name = separator < 0 ? value : value.slice(0, separator)
  const query = separator < 0 ? '' : value.slice(separator + 1)
  const view: WorkspaceView = views.includes(name) ? name as WorkspaceView : 'payments'
  const defaults = defaultPaymentFilters(view, today)
  if (view !== 'payments' && view !== 'history') {
    return { view, filters: defaults, limit: 6, offset: 0, ruleId: null }
  }
  const params = new URLSearchParams(query)
  const rawFrom = params.get('date_from')
  const rawTo = params.get('date_to')
  let dateFrom = rawFrom === null ? defaults.date_from : calendarDate(rawFrom)
  let dateTo = rawTo === null ? defaults.date_to : calendarDate(rawTo)
  const invalidDate = (rawFrom !== null && rawFrom !== '' && !dateFrom) || (rawTo !== null && rawTo !== '' && !dateTo)
  const reversed = Boolean(dateFrom && dateTo && dateFrom > dateTo)
  const invalidSummary = view === 'payments' && (!dateFrom || !dateTo || dateTo > defaults.date_to)
  if (invalidDate || reversed || invalidSummary) {
    dateFrom = defaults.date_from
    dateTo = defaults.date_to
  }
  const currency = params.get('currency') ?? ''
  const status = params.get('status') ?? 'all'
  return {
    view,
    filters: {
      date_from: dateFrom,
      date_to: dateTo,
      currency: currencies.includes(currency) ? currency as PaymentCurrency : '',
      tab: tabs.includes(status) ? status as PaymentTab : 'all',
    },
    limit: pageSize(queryInteger(params.get('limit'))),
    offset: safeOffset(queryInteger(params.get('offset'))),
    ruleId: view === 'history' ? ruleSelection(params.get('recurring_payment_id')) : null,
  }
}

/** Deterministic URLs make filters, page size and page position survive reloads. */
export function paymentHash(view: 'payments' | 'history', filters: PaymentFilters, options: PaymentRouteOptions = {}): string {
  const params = new URLSearchParams()
  const from = calendarDate(filters.date_from)
  const to = calendarDate(filters.date_to)
  if (!from || !to || from <= to) {
    if (from) params.set('date_from', from)
    if (to) params.set('date_to', to)
  }
  if (currencies.includes(filters.currency)) params.set('currency', filters.currency)
  params.set('status', tabs.includes(filters.tab) ? filters.tab : 'all')
  params.set('limit', String(pageSize(options.limit ?? 6)))
  params.set('offset', String(safeOffset(options.offset ?? 0)))
  const ruleId = view === 'history' ? ruleSelection(options.ruleId) : null
  if (ruleId) params.set('recurring_payment_id', ruleId)
  return `#${view}?${params.toString()}`
}

export function viewHash(view: WorkspaceView): string {
  return `#${view}`
}
