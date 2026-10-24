import type { Currency } from '../types/api'
import type { BudgetPeriod } from '../components/BudgetPanel'
import type { ReceiptFilters } from '../components/ReceiptsPanel'

const currencies = ['RUB', 'USD', 'EUR']
export function readBudgetRoute(hash: string, today: string): BudgetPeriod {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  const year = /^\d{1,4}$/.test(params.get('year') || '') ? Number(params.get('year')) : Number(today.slice(0,4))
  const month = /^(?:[1-9]|1[0-2])$/.test(params.get('month') || '') ? Number(params.get('month')) : Number(today.slice(5,7))
  return { year: year >= 1 && year <= 9999 ? year : Number(today.slice(0,4)), month, mode: params.get('mode') === 'year' ? 'year' : 'month' }
}
export function budgetHash(period: BudgetPeriod): string { return '#budget?' + new URLSearchParams({ mode: period.mode, year: String(period.year), month: String(period.month) }) }
export function readReceiptsRoute(hash: string): { filters: ReceiptFilters; offset: number } {
  const params = new URLSearchParams(hash.split('?')[1] || '')
  const rawOffset = params.get('offset') || ''
  return { filters: { query: (params.get('query') || '').slice(0,200), currency: currencies.includes(params.get('currency') || '') ? params.get('currency') as Currency : '', kind: ['file','link','missing'].includes(params.get('kind') || '') ? params.get('kind') as ReceiptFilters['kind'] : 'all' }, offset: /^\d+$/.test(rawOffset) && Number(rawOffset) <= 1_000_000 ? Number(rawOffset) : 0 }
}
export function receiptsHash(filters: ReceiptFilters, offset = 0): string {
  const params = new URLSearchParams()
  if (filters.query) params.set('query', filters.query)
  if (filters.currency) params.set('currency', filters.currency)
  if (filters.kind !== 'all') params.set('kind', filters.kind)
  if (offset) params.set('offset', String(offset))
  return '#receipts' + (params.size ? '?' + params : '')
}
