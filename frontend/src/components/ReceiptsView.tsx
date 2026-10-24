import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { api } from '../api/client'
import type { ReceiptPage } from '../types/extras'
import type { PaymentOccurrence } from '../types/api'
import { readReceiptsRoute, receiptsHash } from '../lib/extras-route'
import { writeWorkspaceHash } from '../lib/useWorkspaceRoute'
import { ReceiptsPanel } from './ReceiptsPanel'
import { ReceiptDrawer } from './ReceiptDrawer'
import { PaymentDrawer } from './PaymentsView'

const subscribe = (callback: () => void) => { window.addEventListener('hashchange', callback); return () => window.removeEventListener('hashchange', callback) }
export function ReceiptsView({ today, timezone, revision, onChanged, onHistory }: { today: string; timezone: string; revision: number; onChanged: () => void; onHistory: (id: string, title: string) => void }) {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash)
  const { filters, offset } = useMemo(() => readReceiptsRoute(hash), [hash])
  const [page, setPage] = useState<ReceiptPage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [retry, setRetry] = useState(0)
  const [editing, setEditing] = useState<PaymentOccurrence | null>(null)
  const [selected, setSelected] = useState<PaymentOccurrence | null>(null)
  useEffect(() => {
    let alive = true
    const timer = setTimeout(() => {
      setLoading(true); setError(null)
      api.listReceipts({ query: filters.query, currency: filters.currency || undefined, kind: filters.kind, limit: 12, offset }).then(value => {
        if (!alive) return
        if (offset > 0 && !value.items.length && value.total <= offset) { writeWorkspaceHash(receiptsHash(filters, Math.max(0, Math.floor((value.total - 1) / 12) * 12)), true); return }
        setPage(value)
      }).catch(reason => { if (alive) setError(reason) }).finally(() => { if (alive) setLoading(false) })
    }, filters.query ? 250 : 0)
    return () => { alive = false; clearTimeout(timer) }
  }, [filters, offset, revision, retry])
  return <><ReceiptsPanel filters={filters} onFiltersChange={value => writeWorkspaceHash(receiptsHash(value))} loading={loading} error={error} onRetry={() => setRetry(value => value + 1)} total={page?.total ?? null} limit={12} offset={offset} onPage={value => writeWorkspaceHash(receiptsHash(filters, value))} items={(page?.items || []).map(({ occurrence, receipt }) => ({ id: occurrence.id, occurrence_id: occurrence.id, title: occurrence.title, amount: occurrence.amount, currency: occurrence.currency, due_date: occurrence.due_date, paid_on: occurrence.paid_on, can_edit: !occurrence.is_cancelled, attachments: receipt ? [{ id: receipt.id, kind: receipt.kind, url: receipt.kind === 'link' ? receipt.url || '' : new URL(api.receiptFileUrl(occurrence.id), window.location.origin).href, label: receipt.filename || 'Ссылка к платежу', file_name: receipt.filename || undefined, size_bytes: receipt.size_bytes ?? undefined }] : [] }))} onEdit={entry => setEditing(page?.items.find(row => row.occurrence.id === entry.occurrence_id)?.occurrence || null)} onOpenPayment={id => setSelected(page?.items.find(row => row.occurrence.id === id)?.occurrence || null)}/>
    {editing && <ReceiptDrawer key={editing.id} item={editing} onClose={() => { setEditing(null); onChanged() }} onChanged={onChanged}/>}
    {selected && <PaymentDrawer key={selected.id} initial={selected} today={today} timezone={timezone} onAttachmentsChanged={onChanged} onClose={() => setSelected(null)} onSaved={() => { setSelected(null); onChanged() }} onHistory={() => onHistory(selected.recurring_payment_id, selected.title)}/>}
  </>
}
