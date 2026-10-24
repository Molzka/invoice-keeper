import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { PaymentsBudget } from '../types/extras'
import { budgetHash, readBudgetRoute } from '../lib/extras-route'
import { paymentHash } from '../lib/payment-route'
import { writeWorkspaceHash } from '../lib/useWorkspaceRoute'
import { BudgetPanel } from './BudgetPanel'

const subscribe = (callback: () => void) => { window.addEventListener('hashchange', callback); return () => window.removeEventListener('hashchange', callback) }
export function BudgetView({ today, revision }: { today: string; revision: number }) {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  const period = useMemo(() => readBudgetRoute(hash, today), [hash, today])
  const [report, setReport] = useState<PaymentsBudget | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    let alive = true
    setLoading(true); setError(null); setReport(null)
    api.getBudget({ year: period.year, ...(period.mode === 'month' ? { month: period.month } : {}) }).then(data => { if (alive) setReport(data) }).catch(reason => { if (alive) setError(reason) }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [period, revision, retry, today])
  return <BudgetPanel period={period} onPeriodChange={value => writeWorkspaceHash(budgetHash(value))} report={report ? { ...report, months: report.months.map(month => ({ ...month, month: `${report.year.toString().padStart(4,'0')}-${month.month.toString().padStart(2,'0')}` })) } : null} loading={loading} error={error} onRetry={() => setRetry(value => value + 1)} onOpenPayments={value => writeWorkspaceHash(paymentHash('history', { date_from: value.date_from, date_to: value.date_to, currency: value.currency, tab: value.status }))}/>
}
