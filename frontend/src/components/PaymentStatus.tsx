import type { PaymentOccurrence } from '../types/api'
import { statusInfo } from '../lib/format'

export function PaymentStatus({ item }: { item: PaymentOccurrence }) {
  if (item.is_cancelled) return <span className="status status-neutral">Удалён</span>
  const info = statusInfo(item)
  const lateClass = item.status === 'paid' && item.paid_late ? ' status-late' : ''
  return <span className={`status ${info.className}${lateClass}`}>{info.text}</span>
}
