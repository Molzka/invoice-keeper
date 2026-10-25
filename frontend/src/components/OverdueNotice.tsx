import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Page, PaymentOccurrence } from '../types/api'
import type { PaymentPageSize } from '../lib/payment-route'
import { paymentHash } from '../lib/payment-route'
import { dateLabel } from '../lib/format'
import { ArrowUpRight } from './BrandIcons'
import { ErrorNotice } from './UI'

export function OverdueNotice({ revision, today, timezone, limit }: { revision: number; today: string; timezone: string; limit: PaymentPageSize }) {
  const [page, setPage] = useState<Page<PaymentOccurrence> | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let alive = true
    setPage(null); setError(null)
    api.listOccurrences({ status: 'unpaid', is_overdue: true, limit: 1, offset: 0 })
      .then(value => { if (alive) setPage(value) })
      .catch(reason => { if (alive) setError(reason) })
    return () => { alive = false }
  }, [revision, today, timezone, retry])
  const href = paymentHash('history', { date_from: '', date_to: '', currency: '', tab: 'overdue' }, { limit })
  return <aside className="overdue-notice" aria-label="Просрочки за всё время" data-overdue={Boolean(page?.total)}>
    <div className="overdue-notice-copy">
      <h2>Просрочки за всё время</h2>
      <p role="status">{error ? 'Не удалось проверить просрочки.' : !page ? 'Проверяем неоплаченные периоды…' : page.total > 0 ? <>Просроченных периодов: <strong>{page.total}</strong>{page.items[0] && <> · самый ранний срок {dateLabel(page.items[0].due_date)}</>}</> : 'Просмотр всех просрочек, включая прошлые месяцы.'}</p>
      {error ? <ErrorNotice error={error} onRetry={() => setRetry(value => value + 1)}/> : null}
    </div>
    <a className="btn btn-secondary" href={href}>Все просрочки<ArrowUpRight size={16} aria-hidden="true"/></a>
  </aside>
}
